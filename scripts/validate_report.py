import json

from flakyhunter.models import Report

with open("sample_results/demo_report.json") as f:
    data = json.load(f)

r = Report.model_validate(data)
print("Schema validates OK")
print(f"total_test_executions: {r.total_test_executions}")
print(f"investigation_execution_count: {r.investigation_execution_count}")

indiv_sum = sum(
    t.polluter_investigation.execution_count for t in r.tests.values() if t.polluter_investigation
)
print(f"Sum of individual execution_counts: {indiv_sum}")
print(f"Match: {r.investigation_execution_count == indiv_sum}")

for nid, t in r.tests.items():
    short = nid.split("::")[-1]
    inv = t.polluter_investigation
    status_line = ""
    if inv:
        status_line = (
            f" | inv_exec={inv.execution_count} verified={inv.verified} status={inv.status}"
        )
    print(
        f"  {short}: flaky={t.is_flaky} p={t.failure_probability} passes={t.passes} failures={t.failures}{status_line}"
    )
