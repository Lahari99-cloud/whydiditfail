from test_company_pipeline import run_corporate_ci_test


def test_company_pipeline_blocks_on_critical_policy():
    assert run_corporate_ci_test() == 1
