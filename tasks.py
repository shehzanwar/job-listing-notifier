"""Task runner (invoke) -- the pip-installable equivalent of the Makefile.

Install:   pip install invoke
Run:       inv <task>          e.g. inv scrape / inv filter / inv calibrate
List all:  inv --list
"""
from invoke import task


@task
def install(c):
    """pip install -r requirements.txt"""
    c.run("python -m pip install -r requirements.txt")


@task
def scrape(c):
    """Run main_scraper.py (all configured Workday companies)."""
    c.run("python main_scraper.py")


@task(name="resume-scrape")
def resume_scrape(c):
    """Scrape only companies not yet in jobs.db after an interrupted run."""
    c.run("python scratch_wave3_remaining.py")


@task
def filter(c):
    """Run main_filter.py (Layer 1+2+LLM, posts to Discord)."""
    c.run("python main_filter.py")


@task
def digest(c):
    """Run main_digest.py (weekly LLM-summarized digest)."""
    c.run("python main_digest.py")


@task
def inspect(c):
    """Data-quality check on jobs.db (HTML residue, empty descriptions, etc.)."""
    c.run("python scratch_inspect.py")


@task(name="filter-test")
def filter_test(c):
    """Layer 1+2 only (title + regex), no LLM/GPU -- shows what volume reaches the LLM."""
    c.run("python scratch_filter_test.py")


@task
def calibrate(c):
    """Run the LLM judge over all Layer 1+2 survivors, write results to CSV."""
    c.run("python scratch_llm_calibrate.py")


@task(name="llm-server-start")
def llm_server_start(c):
    """Start llama-server detached (survives across separate invoke calls)."""
    c.run("python -m utils.llm_server_ctl start")


@task(name="llm-server-status")
def llm_server_status(c):
    """Check whether llama-server is running and healthy."""
    c.run("python -m utils.llm_server_ctl status")


@task(name="llm-server-stop")
def llm_server_stop(c):
    """Stop the detached llama-server."""
    c.run("python -m utils.llm_server_ctl stop")


@task
def clean(c):
    """Remove __pycache__ and *.pyc."""
    import pathlib
    import shutil

    for p in pathlib.Path(".").rglob("__pycache__"):
        shutil.rmtree(p, ignore_errors=True)
    for p in pathlib.Path(".").rglob("*.pyc"):
        p.unlink(missing_ok=True)
    print("Cleaned __pycache__ and *.pyc")
