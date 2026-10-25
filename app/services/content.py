"""Static, public, non-sensitive content: FAQ and help articles (shared by the landing
page, the help centre and global search). Safe to cache publicly."""
from __future__ import annotations

FAQ: list[tuple[str, str]] = [
    ("What is a Unique Patient ID (UPI)?",
     "It's the ID you get when you sign up, like CDH-K2AV-ZHSF-P7YN. Give it to a doctor so they can find your records. It contains a check code, so a mistyped ID is caught instead of opening someone else's file."),
    ("Who can see my records?",
     "You decide per record. Public records can be read by verified clinicians who have your UPI. Private records can only be read by a doctor you approve, for the time you choose and only until they sign out, or in a logged emergency."),
    ("How does approving a doctor work?",
     "The doctor sends a request with a reason. You choose how long access lasts, then confirm with a 6-digit code we text to your phone. You can revoke access at any time and it stops immediately."),
    ("What happens in an emergency?",
     "A verified doctor can open your records without approval only by declaring an emergency and giving a reason. Access lasts one hour, you are notified, and it appears in red in your access history."),
    ("Can I see who looked at my records?",
     "Yes. Your access history shows every view, download or change by someone else, with the date, the person and the hospital."),
    ("Can a doctor register on CDHRS by themselves?",
     "No. Doctor and staff accounts are created by their hospital's administrator, who checks their licence. This keeps impostors out."),
    ("Can I delete a record?",
     "You can delete documents you uploaded yourself. Records written by a doctor are part of your medical record, so you can make them private but not delete them."),
    ("Is my data safe?",
     "Passwords are hashed, sessions expire after inactivity, every important action is audited, and pages with health data are never stored in shared caches."),
]

HELP: list[dict[str, str]] = [
    {"id": "upi", "title": "Finding and sharing your patient ID", "body": "Your UPI is on your dashboard health card. Use the copy button and share it with your doctor."},
    {"id": "upload", "title": "Uploading a document", "body": "Go to Upload a document, choose a PDF or image up to 10 MB, add a title and choose public or private."},
    {"id": "visibility", "title": "Making a record public or private", "body": "Open the record and use the switch under 'Who can see this record'. Every change is kept in the record's update history."},
    {"id": "consent", "title": "How consent works", "body": "Doctors request access with a purpose. You approve, pick a duration and confirm with an SMS code. Access ends when that time is up or when the doctor signs out, whichever comes first; their next visit needs a new request. Revoke any time from Access requests."},
    {"id": "emergency", "title": "Emergency access", "body": "Verified doctors can use emergency access with a written reason. It lasts one hour, is logged, flagged in red and you are notified."},
    {"id": "history", "title": "Reading your access history", "body": "Access history lists who opened or changed your records. Use the Emergency only filter to see emergency events."},
    {"id": "password", "title": "Changing your password", "body": "Open Profile & security. Changing your password signs you out on all other devices."},
    {"id": "doctor-search", "title": "Finding a patient (clinicians)", "body": "Enter the patient's full UPI. Partial IDs and names are not searchable, to protect privacy."},
    {"id": "doctor-account", "title": "Getting a doctor account", "body": "Ask your hospital administrator. They create your account with your email, designation and licence number."},
]
