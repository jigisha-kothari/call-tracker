import urllib.request
import urllib.error
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
import os
import sys

IST = timezone(timedelta(hours=5, minutes=30))
today = datetime.now(IST).strftime('%Y-%m-%d')
today_display = datetime.now(IST).strftime('%d %b %Y')

access_token = os.environ['ZOHO_ACCESS_TOKEN']

# Fetch calls from Zoho CRM
query = (
    "SELECT id, Subject, Call_Duration, Call_Duration_in_seconds, "
    "Call_Start_Time, Call_Type, Owner FROM Calls "
    "WHERE Call_Start_Time >= '" + today + "T00:00:00+05:30' "
    "AND Call_Start_Time <= '" + today + "T23:59:59+05:30' "
    "ORDER BY Call_Start_Time ASC LIMIT 200"
)

req = urllib.request.Request(
    'https://www.zohoapis.eu/crm/v3/coql',
    data=json.dumps({'select_query': query}).encode(),
    headers={
        'Authorization': 'Zoho-oauthtoken ' + access_token,
        'Content-Type': 'application/json'
    }
)

try:
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read())
except urllib.error.HTTPError as e:
    print("Zoho API error: " + str(e.code) + " " + str(e.read()))
    sys.exit(1)

calls = data.get('data', [])


def fmt_dur(s):
    if not s or int(s) == 0:
        return '0s'
    s = int(s)
    m, sec = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return str(h) + 'h ' + str(m) + 'm ' + str(sec) + 's'
    if m:
        return str(m) + 'm ' + str(sec) + 's'
    return str(sec) + 's'


def fmt_time(t):
    dt = datetime.fromisoformat(t).astimezone(IST)
    return dt.strftime('%H:%M')


def contact_name(subject):
    if not subject:
        return 'Unknown'
    s = subject.replace('Outgoing call to ', '').replace('Incoming call from ', '')
    return s.split(' (+')[0].split(' (')[0].strip()


connected = [c for c in calls if (c.get('Call_Duration_in_seconds') or 0) > 0]
not_connected = len(calls) - len(connected)
total_seconds = sum(int(c.get('Call_Duration_in_seconds') or 0) for c in connected)
avg_seconds = total_seconds // len(connected) if connected else 0

# Call log
call_lines = []
for i, c in enumerate(calls, 1):
    dur = int(c.get('Call_Duration_in_seconds') or 0)
    status = 'Connected' if dur > 0 else 'Not Connected'
    name = contact_name(c.get('Subject', ''))
    owner = (c.get('Owner') or {}).get('name', '')
    call_lines.append(
        str(i) + '. ' + fmt_time(c['Call_Start_Time']) +
        ' — ' + name + ' (' + owner + ')' +
        ' — ' + fmt_dur(dur) + ' — ' + status
    )

# Gap breaches: >30 min between consecutive connected calls within business hours
breach_lines = []
cs = sorted(connected, key=lambda c: c['Call_Start_Time'])
for i in range(1, len(cs)):
    prev_dt = datetime.fromisoformat(cs[i-1]['Call_Start_Time']).astimezone(IST)
    curr_dt = datetime.fromisoformat(cs[i]['Call_Start_Time']).astimezone(IST)
    gap = (curr_dt - prev_dt).total_seconds()
    biz_start = prev_dt.replace(hour=9, minute=0, second=0, microsecond=0)
    biz_end = prev_dt.replace(hour=18, minute=0, second=0, microsecond=0)
    if gap > 1800 and prev_dt >= biz_start and curr_dt <= biz_end:
        pn = contact_name(cs[i-1].get('Subject', ''))
        cn = contact_name(cs[i].get('Subject', ''))
        breach_lines.append(
            '  - ' + fmt_time(cs[i-1]['Call_Start_Time']) +
            ' to ' + fmt_time(cs[i]['Call_Start_Time']) +
            ' — ' + fmt_dur(gap) + ' gap (after ' + pn + ', before ' + cn + ')'
        )

call_log_text = '\n'.join(call_lines) if call_lines else 'No calls recorded today.'

body = (
    'End of Day Call Summary — ' + today_display + '\n\n'
    'OVERVIEW\n'
    'Total Calls: ' + str(len(calls)) + '\n'
    'Connected: ' + str(len(connected)) + '\n'
    'Not Connected: ' + str(not_connected) + '\n'
    'Total Talk Time: ' + fmt_dur(total_seconds) + '\n'
    'Avg Call Duration: ' + fmt_dur(avg_seconds) + '\n\n'
    'CALL LOG\n' + call_log_text
)

if breach_lines:
    body += '\n\nGAP BREACHES\n' + '\n'.join(breach_lines)

body += '\n\n—\nSent automatically by Call Tracker'

# Send via Zoho SMTP
msg = MIMEMultipart()
msg['From'] = os.environ['SMTP_USER']
msg['To'] = 'admin@kendraintl.onmicrosoft.com, j.kothari@kendra-intl.com'
msg['Subject'] = 'Call Summary Report — ' + today_display
msg.attach(MIMEText(body, 'plain'))

with smtplib.SMTP_SSL('smtp.zoho.eu', 465) as server:
    server.login(os.environ['SMTP_USER'], os.environ['SMTP_PASS'])
    server.sendmail(
        os.environ['SMTP_USER'],
        ['admin@kendraintl.onmicrosoft.com', 'j.kothari@kendra-intl.com'],
        msg.as_string()
    )

print('Report sent for ' + today_display + ' — ' + str(len(calls)) + ' calls, ' + str(len(connected)) + ' connected.')
