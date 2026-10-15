---
# AnyHealth Workforce Self-Service (sample knowledge)
#
# Grounds the INTERNAL staff vignettes: Clock In/Out, My Schedule,
# PTO Request, and Shift Swap. These demonstrate RCS for employee/staff
# use cases, alongside the customer-facing vignettes in the other content
# files. Illustrative sample data for a fictitious employee — not a real
# person or real HR data. Edit freely.
employeeName: "Marcus Chen"
employeeRole: "Patient Services Representative"
employeeId: "EMP-4821"
department: "Patient Services"
location: "AnyHealth Chestnut St Clinic"
locationLat: 39.9500
locationLng: -75.1650
managerName: "Priya Nair"
managerTitle: "Patient Services Supervisor"

# PTO (paid time off) balance shown in the PTO Request flow.
ptoBalanceDays: 12
ptoBalanceUsedDays: 6

# Upcoming shifts shown in My Schedule and used as the source list for
# Shift Swap (a shift the employee already owns can be offered for swap).
shifts:
  - id: "shift_mon"
    day: "Monday"
    date: "July 14"
    isToday: false
    start: "8:00 AM"
    end: "4:00 PM"
    role: "Front Desk"
  - id: "shift_wed"
    day: "Wednesday"
    date: "July 16"
    isToday: false
    start: "10:00 AM"
    end: "6:00 PM"
    role: "Check-In"
  - id: "shift_fri"
    day: "Friday"
    date: "July 18"
    isToday: false
    start: "8:00 AM"
    end: "4:00 PM"
    role: "Front Desk"
  - id: "shift_sat"
    day: "Saturday"
    date: "July 19"
    isToday: false
    start: "9:00 AM"
    end: "1:00 PM"
    role: "Check-In"

# Coworkers offered as swap partners in the Shift Swap flow. Each has one
# open shift that could plausibly be traded for one of the employee's own.
coworkers:
  - id: "coworker_dana"
    name: "Dana Whitfield"
    role: "Patient Services Representative"
    openShiftLabel: "Thursday, July 17, 12:00 PM – 8:00 PM"
  - id: "coworker_leo"
    name: "Leo Ferraro"
    role: "Patient Services Representative"
    openShiftLabel: "Sunday, July 20, 9:00 AM – 5:00 PM"
  - id: "coworker_priya_backup"
    name: "Alicia Reyes"
    role: "Patient Services Representative"
    openShiftLabel: "Tuesday, July 15, 8:00 AM – 4:00 PM"

# Tone for any AI-assisted copy touching this content (none of the 4 internal
# vignettes are AI-driven today, but keep this for consistency with the other
# content files).
tone: "Direct and efficient. This is an internal staff tool, not a member-facing one — skip the pleasantries."
---

# AnyHealth Workforce Self-Service

Sample data for four **internal, employee-facing** RCS vignettes that sit
alongside AnyHealth's customer-facing scenarios: Clock In/Out, My Schedule,
PTO Request, and Shift Swap. These show that the same RCS channel used for
member/customer messaging also works well for internal staff workflows —
attendance, scheduling, time-off requests, and shift coordination — without
any dedicated workforce app.

All names, shifts, PTO balances, and coworkers below are illustrative demo
data for a fictitious clinic employee. Edit the frontmatter above to change
the roster, shifts, or balances.
