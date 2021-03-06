"""Send an email message from the user's account.
"""
#Auth
import os
import pickle
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

#Email
import base64
from email.mime.text import MIMEText
from string import Template

#Calendar
from datetime import datetime, timedelta
from pytz import timezone

#APIclient
from apiclient import errors

#USER VARIABLES
from config import * #(DON'T DO THIS IN PRODUCTION-GRADE CODE)
IS_IN_TEST_MODE = True

def createTemplates():
	"""Create email Template objects"""
	
	msg_template = ""
	with open(PATH_TO_MSG_TEMPLATE) as file:
		msg_template = Template(file.read())
		
	subject_template = Template(SUBJECT_TEMPLATE)
	
	return (msg_template, subject_template)


def CreateMessage(sender, to, subject, message_text, cc='', bcc=''):
  """Create a message for an email.

  Args:
    sender: Email address of the sender.
    to: Email address of the receiver.
    subject: The subject of the email message.
    message_text: The text of the email message.
	cc: Email address(es) of CC (Optional)
	bcc: Email address(es) of BCC (Optional)

  Returns:
    An object containing a base64url encoded email object.
  """
  message = MIMEText(message_text, 'html')
  message['to'] = to
  message['cc'] = cc
  message['bcc'] = bcc
  message['from'] = sender
  message['subject'] = subject
  return {'raw': base64.urlsafe_b64encode(message.as_string().encode()).decode()}

def SendMessage(service, user_id, message):
  """Send an email message.

  Args:
    service: Authorized Gmail API service instance.
    user_id: User's email address. The special value "me"
    can be used to indicate the authenticated user.
    message: Message to be sent.

  Returns:
    Sent Message.
  """
  try:
    message = (service.users().messages().send(userId=user_id, body=message)
               .execute())
    print ('Message Id: %s' % message['id'])
    return message
  except errors.HttpError as error:
    print ('An error occurred: %s' % error)

##Google API Permissions
SCOPES = ['https://www.googleapis.com/auth/gmail.send', #Gmail - send
			'https://www.googleapis.com/auth/calendar.readonly', #Calendar - read-only
			'https://www.googleapis.com/auth/spreadsheets.readonly'] #Sheets - read-only

def auth():
	"""Authenticate into Google API services"""
	creds = None
	# The file token.pickle stores the user's access and refresh tokens, and is
	# created automatically when the authorization flow completes for the first
	# time.
	if os.path.exists('token.pickle'):
		with open('token.pickle', 'rb') as token:
			creds = pickle.load(token)
    # If there are no (valid) credentials available, let the user log in.
	if not creds or not creds.valid:
		if creds and creds.expired and creds.refresh_token:
			creds.refresh(Request())
		else:
			flow = InstalledAppFlow.from_client_secrets_file(
				'credentials.json', SCOPES)
			#flow.user_agent = APPLICATION_NAME
			creds = flow.run_local_server(port=0)
		# Save the credentials for the next run
		with open('token.pickle', 'wb') as token:
			pickle.dump(creds, token)
	
	return creds


def main():
	creds = auth()
	
	msg_template, subject_template = createTemplates()
	
	#Build google services
	gmail_svc = build('gmail', 'v1', credentials=creds)
	calendar_svc = build('calendar', 'v3', credentials=creds)
	sheets_svc = build('sheets', 'v4', credentials=creds)
	
	#Retrieve Calendar events
	now = datetime.utcnow().isoformat() + TIMEZONE_STR
	day_later = (datetime.utcnow() + timedelta(hours=24)).isoformat() + TIMEZONE_STR
	
	#Get next day's events
	events_result = calendar_svc.events().list(calendarId='primary', timeMin=now, timeMax=day_later,
                                        maxResults=10, singleEvents=True,
                                        orderBy='startTime').execute()
	events = events_result.get('items', [])
	
	tutoring_events = []
	if not events:
		print('No upcoming events on calendar.')
	for event in events:
		start = event['start'].get('dateTime', event['start'].get('date'))
		#Ensure Trilogy bootcamp session
		if EVENT_DESCRIPTION not in event['description']:
			continue
		#Check for cancellation
		if 'Canceled' in event['summary']:
			continue
		tutoring_events.append(event)
		
	if not tutoring_events:
		print('No upcoming tutoring sessions found.')
		return
	
	#Retrieve timezone from Sheets
	sheet = sheets_svc.spreadsheets()
	result = sheet.values().get(spreadsheetId=SHEET_NAME, range=RANGE_NAME).execute()
	values = result.get('values', [])
	
	student_data = {}
	if not values:
		print("No Sheets data found. Check your RANGE_NAME to ensure you're looking in the right place in your Sheet.")
	else:
		for row in values:
			try:
				student_data[row[EMAIL_COLUMN]] = (row[NAME_COLUMN], row[TZ_COLUMN], row[ZOOM_COLUMN])
			except:
				print('If range out of index error, ensure there is data in each of the columns above for each student!')

	#Send confirmation email for each event
	for event in tutoring_events:
		student_email = ""
		for attendee in event['attendees']:
			if attendee['email'] != TUTOR_EMAIL: #2 attendees, ignore tutor
				student_email = attendee['email']
		#Lookup email in Sheets data
		while student_email != 'skip' and student_email not in student_data:
			print(f"Email {student_email} not found. If you know who this is, please supply the email address they registered with or enter 'skip' to skip to the next session.")
			student_email = input()
		if student_email == 'skip':
				continue
		
		#Get first name and timezone offset
		student_name = student_data[student_email][0]
		student_tz = student_data[student_email][1]
		student_zoom = student_data[student_email][2] #TODO: Test to ensure value?
		
		student_firstname = student_name.split(' ')[0]
		
		tz = ""	
		if 'CST' in student_tz:
			tz = timezone('US/Central')
		elif 'EST' in student_tz:
			tz = timezone('US/Eastern')
		elif 'MST' in student_tz:
			tz = timezone('US/Mountain')
		elif 'PST' in student_tz:
			tz = timezone('US/Pacific')
		else:
			print(f"Unable to interpret timezone. Please enter the timezone for {student_name} in pytz format (https://gist.github.com/heyalexej/8bf688fd67d7199be4a1682b3eec7568).")
			tz = timezone(input())
		
		
		event_start_raw = event['start'].get('dateTime', event['start'].get('date'))
		event_start_dt = datetime.strptime(event_start_raw, '%Y-%m-%dT%H:%M:%S%z').astimezone(tz)
		event_end_dt = event_start_dt + timedelta(minutes=50)
		
		event_date = event_start_dt.strftime('%A, %B %d')
		event_start = event_start_dt.strftime('%I:%M')
		event_end = event_end_dt.strftime('%I:%M%p %Z')
		
		msg_text = msg_template.substitute(name=student_firstname,
						date=event_date, starttime=event_start, endtime=event_end, zoomlink=student_zoom)
		
		subject_text = subject_template.substitute(date=event_date, starttime=event_start, endtime=event_end)
	
		message = None
		if IS_IN_TEST_MODE:
			message = CreateMessage(sender=TUTOR_SENDER, to=TEST_EMAIL, subject=subject_text, message_text=msg_text)
		else:
			message = CreateMessage(sender=TUTOR_SENDER, to=student_email, subject=subject_text, message_text=msg_text, cc='centraltutorsupport@bootcampspot.com')
			
		SendMessage(gmail_svc, 'me', message)
	
	if IS_IN_TEST_MODE:
		print('Test complete. Hope it worked!')
	
if __name__ == "__main__":
	main()