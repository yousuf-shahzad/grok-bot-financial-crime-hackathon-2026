"""Our condensed reading of the bank's identity SOP (SPEC.md sections 3 to 5), in our own words.
Shared by the LLM judge, the screening agent and the demo's LLM court."""

SOP = """Identity only: is this watchlist hit the bank's customer? Never judge how serious the listing is.
Wrongly clearing a real match is by far the worst error, so when in doubt the answer is ESCALATE.
CLEAR (different entity) only on a contradiction the SOP names:
- type: one is a person, the other a company;
- death: the profile gives a date of death before the customer was screened;
- time: the customer was under 16 (or the company not yet incorporated) at the earliest dated report;
- date of birth: EVERY birth date the hit gives is contradicted (customer year more than 1 year outside it,
  or same year with a different month or day); one agreeing date blocks this;
- name: the customer's VERIFIED legal name agrees with none of the hit's names or aliases;
- location: every country tied to the customer (residence, nationality, verified document country, places
  notes say they lived) differs from every country tied to the hit; BUT if name and date of birth agree,
  a country difference does not clear.
CONFIRM (same entity) only on agreement with nothing contradicting: a person needs name AND date of birth
to agree (birth year is one of the hit's possible years and every part both give is equal); a company needs
name AND country to agree.
Names agree when at least two name parts match, or every part of the shorter name matches; parts match if
identical, known variants, joined/split, or 1 edit (4-6 letters) / 2 edits (7+). Initials and placeholders
are not parts; a person with fewer than 2 real name parts can be neither confirmed nor cleared on name.
Unknown stays unknown: a missing field or a missing part of a date is never a mismatch.
Verified beats declared: an approved identity check outranks what the customer typed; rejected or expired
checks are not evidence."""
