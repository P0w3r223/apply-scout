# Candidate CV — synthetic evaluation fixture

> Synthetic profile used only to drive the evaluation harness. Every skill below is
> backed by a real, public repository under GitHub `P0w3r223`, so `github_evidence`
> can match requirements against genuine repos. It contains no real personal data.

**Role target:** AI Engineer / Data Scientist / Machine-Learning Engineer
**GitHub:** https://github.com/P0w3r223
**Location:** Wrocław, Poland — open to remote

## Summary

Python engineer who ships end-to-end machine-learning and data projects: from data
collection and modelling through evaluation, packaging, and CI. Comfortable owning the
boring parts that make a model trustworthy — reproducible pipelines, measured baselines,
honest error analysis — as well as the applied-LLM parts (agent loops, structured
outputs, guardrails). Strong bias toward small, tested, well-documented code.

## Core skills

- **Languages:** Python (primary), SQL, C++, Bash
- **Machine learning:** scikit-learn, RandomForest / gradient boosting, regression,
  feature engineering, model evaluation and error analysis
- **MLOps:** MLflow experiment tracking and model registry, reproducible training
  pipelines, artifact/version pinning, CI for ML
- **NLP:** text classification, sentiment analysis, TF-IDF baselines, transformer
  fine-tuning (HerBERT), macro-F1 evaluation
- **Applied LLM / agents:** Anthropic API, from-scratch tool loops, structured outputs
  with validate-and-retry, anti-hallucination guardrails, trajectory-based evaluation
- **Statistics / experimentation:** A/B testing, hypothesis testing, power analysis,
  sequential-testing pitfalls (peeking), scipy/statsmodels
- **Data engineering:** web scraping, ETL, SQLite, schema design, data validation
  (Pydantic)
- **Tooling:** Git, Docker, pytest, ruff, GitHub Actions, uv/venv, argparse CLIs
- **Systems / networking:** raw sockets, ICMP/UDP, low-level packet handling (C++)

## Selected projects (public, on GitHub `P0w3r223`)

- **apply-scout** — LLM agent matching a job posting against a CV and GitHub evidence.
  From-scratch tool loop (no framework), safety budgets, JSONL trajectory log, and a
  trajectory-evaluation harness (requirement-F1, citation fidelity, cost). *Python,
  Anthropic API, Pydantic, pytest.*
- **mlops-car-price** — MLOps layer over a used-car price model: MLflow tracking +
  registry, reproducible training, model/data versioning, 111 tests, green CI.
  *Python, scikit-learn, MLflow.*
- **ab-lab** — A/B-testing statistics package: two-proportion / two-mean tests, power
  and sample-size, sequential-testing (peeking) correction, 179 tests. *Python, scipy,
  statsmodels.*
- **pl-review-sense** — Polish-review sentiment: TF-IDF baseline (macro-F1 ≈ 0.94)
  compared against a HerBERT transformer fine-tune. *Python, scikit-learn, transformers.*
- **car-price-ml** — used-car price regression on a Kaggle CC0 dataset; RandomForest
  best; clean train/validate methodology. *Python, scikit-learn, pandas.*
- **it-job-radar** — IT-job-market ETL: scrapes postings, normalises them into SQLite,
  rule-based field extraction (seniority, tech stack, contract, salary). *Python,
  scraping, SQLite.*
- **token-budget** — stdlib CLI that parses agent transcripts and gates token spend
  against milestone budgets. *Python, argparse.*
- **auth-log-scan** — SSH auth-log scanner (stdlib only): brute-force / credential-spray
  / anomaly detectors over `/var/log/auth.log`. *Python.*
- **mini-traceroute** — raw-socket traceroute in modern C++ (UDP probes, ICMP replies,
  per-hop RTT). *C++.*
- **wroclaw-air-insights** — air-quality data analysis and visualisation for Wrocław.
  *Python, pandas, data viz.*

## Experience (representative)

**Independent / portfolio engineering** — *2024–present*
Designed and shipped the ten public projects above across ML, MLOps, applied LLMs,
statistics, data engineering, and systems programming. Each ships with tests, CI, an
honest limitations section, and ADRs recording the key design decisions.

## Education

BSc-level computer science coursework with a focus on machine learning, statistics, and
software engineering (self-directed continuation through the portfolio above).
