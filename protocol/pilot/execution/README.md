# Draft execution packets

These eight JSON packets are generated from the proposed cases by `scripts/prepare_pilot_packets.py`. They contain selected native tasks, software identity, setup proposals and allowed public documentation. They contain no independently selected source records, expected values, fixtures or checker feedback. Native example inputs remain task parameters, not expected answers.

All packets are `draft_not_authorized`. Do not give an executor the complete repository, case-preparation memos, assessment-design implementation or assessor conversation. Before use, create a fresh executor context with only the approved packet, permitted public software/documentation and a qualified restricted tool interface. The parent coordinator must control packet delivery and hold-out access separately. File separation is not an access boundary.

The runtime, dependencies, source observation window and output capture must be fixed before execution. A future lock manifest must identify the approved packet hashes and actual runtime, rather than treating these draft hashes as approval.
