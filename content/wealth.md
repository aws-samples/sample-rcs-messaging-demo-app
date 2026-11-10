---
# AnyWealth Account Servicing (sample knowledge)
#
# Grounds the AnyWealth vignettes, including the Fraud Alert
# (wealth_fraud_alert): a verified-sender fraud alert rich card with
# "Yes/No it was me" replies and an expiring one-time code. Demonstrates RCS
# for financial services — where a verified sender identity is the whole point:
# the handset shows the member this really is their bank, not a smishing text.
# Illustrative sample data for a fictitious member, account, and transaction —
# not a real person, bank, or financial data. Edit freely.
memberName: "Priya Raman"
accountNickname: "Everyday Checking"
accountNumberMasked: "****5190"
cardNumberMasked: "****4417"

# The flagged transaction that drives the fraud-alert card. The member is
# asked to confirm "Yes, it was me" or "No, it wasn't" with suggested replies,
# and an expiring code is shown for step-up verification.
flaggedTransaction:
  id: "txn_fraud_0001"
  merchant: "Nova Electronics Online"
  amount: 849.00
  currency: "USD"
  city: "Austin, TX"
  dateTime: "Today, 2:14 PM"
  channel: "Card not present"
  reason: "Unusually large purchase far from your usual activity."

# Recent transactions the member can review in account-servicing copy. All
# amounts are sample figures.
recentTransactions:
  - id: "txn_001"
    merchant: "Riverside Grocery"
    amount: 62.48
    dateTime: "Today, 9:05 AM"
    status: "Posted"
  - id: "txn_002"
    merchant: "Metro Transit"
    amount: 5.00
    dateTime: "Yesterday, 6:42 PM"
    status: "Posted"
  - id: "txn_003"
    merchant: "Brightside Coffee"
    amount: 4.75
    dateTime: "Yesterday, 8:11 AM"
    status: "Posted"

# Account snapshot for account-servicing answers.
account:
  availableBalance: 3284.17
  currency: "USD"
  statementBalance: 1120.55
  statementDueDate: "September 2"

# One-time code settings for the step-up verification shown in the fraud alert.
# The code itself is generated at runtime; this only controls how long it lives.
otpTtlSeconds: 300

# Support details the member can reach when a transaction is not theirs.
fraudLinePhone: "+18005550103"

# Tone for any AI-assisted copy touching this content.
tone: "Calm, clear, and reassuring. Never alarmist. Give the member a simple next step and make it obvious how to reach a human."
---

# AnyWealth Account Servicing

Sample data for AnyWealth's financial-services vignettes, centered on the
**Fraud Alert**: a verified-sender rich card tells the member about a flagged
transaction, offers "Yes, it was me" / "No, it wasn't" replies, and shows an
expiring one-time code for step-up verification — all inside the RCS
conversation. The verified sender identity is the point: the handset renders
AnyWealth's registered brand so the member can trust the message is really from
their bank and not a smishing attempt.

The member, account, and transactions below are illustrative demo data for a
fictitious person and bank. Edit the frontmatter above to change the flagged
transaction, the account snapshot, or the support contact.

**No real account data is used and no money moves.** Balances, card numbers,
and transactions are sample figures. The demo never asks for, receives, or
stores real financial credentials; a real deployment would integrate with a
bank's own systems behind proper authentication rather than carrying account
data in content files.
