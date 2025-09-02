from pathlib import Path


def test_run_all_outputs_single_dir(tmp_path, monkeypatch):
    from pipeline import __main__ as main

    # Avoid network and heavy work by mocking pipeline steps
    monkeypatch.setattr(main, "fetch_feeds", lambda since, max_items, logger: {})
    monkeypatch.setattr(
        main, "extract_step", lambda limit, parallel, logger: 0
    )
    monkeypatch.setattr(main, "cluster_step", lambda logger: [])

    dummy_summary = [
        {"cluster_id": 1, "bullets": ["b1"], "citations": []}
    ]
    monkeypatch.setattr(main, "summarize", lambda logger: dummy_summary)
    monkeypatch.setattr(
        main,
        "score_clusters",
        lambda: [{"cluster_id": 1, "score": 1.0, "size": 1}],
    )

    main.run_all(
        out=tmp_path,
        since=None,
        max_items=None,
        dry_run=False,
        log_level="INFO",
        parallel=1,
    )

    run_dirs = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    assert (run_dir / "summaries.md").exists()
    # Ensure results are written directly to run_dir, not a nested run_dir
    timestamp_dirs = [
        p
        for p in run_dir.iterdir()
        if p.is_dir() and p.name[:4].isdigit() and p.name[4] == "-"
    ]
    assert not timestamp_dirs

