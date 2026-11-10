---
# AnyHR Workforce Self-Service (sample knowledge)
#
# Grounds the AnyHR staff vignettes: Clock In/Out, My Schedule, PTO
# Request and Shift Swap. AnyHR is HR software that works for any
# workforce; this sample models one fictitious retail employer, Maple
# Street Market. Illustrative data for a fictitious employee, not a real
# person or real HR data. Edit freely.
employer: "Maple Street Market"
employeeName: "Jordan Blake"
employeeRole: "Store Associate"
employeeId: "EMP-4821"
department: "Store Operations"
location: "Maple Street Market, Downtown Store"
locationLat: 41.8827
locationLng: -87.6233
managerName: "Taylor Brooks"
managerTitle: "Store Manager"

# PTO (paid time off) balance shown in the PTO Request flow.
ptoBalanceDays: 12
ptoBalanceUsedDays: 6

# Upcoming shifts shown in My Schedule and used as the source list for
# Shift Swap (a shift the employee already owns can be offered for swap).
# The day name, the date and the "today" flag are NOT written here: the
# code computes them from `dayOffset` (days from today), so the sample
# schedule is always upcoming. Keep each `id`: the swap postbacks
# (swap_shift_<id>) carry it.
shifts:
  - id: "shift_mon"
    dayOffset: 1
    start: "8:00 AM"
    end: "4:00 PM"
    role: "Cashier"
  - id: "shift_wed"
    dayOffset: 3
    start: "10:00 AM"
    end: "6:00 PM"
    role: "Stock"
  - id: "shift_fri"
    dayOffset: 5
    start: "8:00 AM"
    end: "4:00 PM"
    role: "Cashier"
  - id: "shift_sat"
    dayOffset: 6
    start: "9:00 AM"
    end: "1:00 PM"
    role: "Customer Service"

# Coworkers offered as swap partners in the Shift Swap flow. Each has one
# open shift that could plausibly be traded for one of the employee's own.
# `openShift.dayOffset` counts days from today, like the shifts above.
coworkers:
  - id: "coworker_dana"
    name: "Dana Whitfield"
    role: "Store Associate"
    openShift: { dayOffset: 2, start: "12:00 PM", end: "8:00 PM" }
  - id: "coworker_leo"
    name: "Leo Ferraro"
    role: "Store Associate"
    openShift: { dayOffset: 4, start: "9:00 AM", end: "5:00 PM" }
  - id: "coworker_priya_backup"
    name: "Alicia Reyes"
    role: "Store Associate"
    openShift: { dayOffset: 3, start: "12:00 PM", end: "8:00 PM" }

# Tone for AI-assisted copy touching this content: the HR assistant's replies
# (common.assistant_facts passes it on).
tone: "Direct and efficient. This is an internal staff tool, not a customer-facing one, so skip the pleasantries."
---

# AnyHR Workforce Self-Service

Sample data for four **internal, employee-facing** RCS vignettes: Clock
In/Out, My Schedule, PTO Request and Shift Swap. They show that the RCS
channel works well for staff workflows (attendance, scheduling, time-off
requests and shift coordination) without a dedicated workforce app.

AnyHR is HR and employee-management software for any workforce. This sample
uses one fictitious retail employer, Maple Street Market, and one employee,
a store associate at its downtown store.

All names, shifts, PTO balances and coworkers are illustrative demo data.
Edit the frontmatter above to change the roster, shifts or balances. Shift
days and dates are computed from each `dayOffset`, so the schedule always
looks current.
