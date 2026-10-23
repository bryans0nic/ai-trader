import scrape_new_recs


def test_second_cli_run_skips_site_and_says_why(monkeypatch, capsys):
    visits = []
    monkeypatch.setattr(scrape_new_recs, "scrape_stock_advisor_rows", lambda: visits.append(1) or [])
    scrape_new_recs.main()
    scrape_new_recs.main()
    out = capsys.readouterr().out
    assert len(visits) == 1
    assert "Skipped: the site was visited less than 15 min ago" in out
