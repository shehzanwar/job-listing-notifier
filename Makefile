.DEFAULT_GOAL := help

# Override on invocation if `python` isn't on PATH, e.g.:
#   make scrape PYTHON="py -3"
PYTHON ?= python

.PHONY: help install scrape filter digest resume-scrape inspect filter-test \
        llm-server-start llm-server-stop llm-server-status calibrate clean

help:
	@echo "Targets:"
	@echo "  install           pip install -r requirements.txt"
	@echo ""
	@echo "  scrape            run main_scraper.py (all configured Workday companies)"
	@echo "  resume-scrape     scrape only companies not yet in jobs.db after an interrupted run"
	@echo "  filter            run main_filter.py (Layer 1+2+LLM, posts to Discord)"
	@echo "  digest            run main_digest.py (weekly LLM-summarized digest)"
	@echo ""
	@echo "  inspect           data-quality check on jobs.db (HTML residue, empty descriptions, etc.)"
	@echo "  filter-test       Layer 1+2 only (title + regex), no LLM/GPU -- shows what volume reaches the LLM"
	@echo "  calibrate         run the LLM judge over all Layer 1+2 survivors, write results to CSV"
	@echo ""
	@echo "  llm-server-start  start llama-server detached (survives across separate make calls)"
	@echo "  llm-server-status check whether llama-server is running and healthy"
	@echo "  llm-server-stop   stop the detached llama-server"
	@echo ""
	@echo "  clean             remove __pycache__ and *.pyc"
	@echo ""
	@echo "Override the python command with PYTHON, e.g.: make scrape PYTHON=\"py -3\""

install:
	$(PYTHON) -m pip install -r requirements.txt

scrape:
	$(PYTHON) main_scraper.py

resume-scrape:
	$(PYTHON) scratch_wave3_remaining.py

filter:
	$(PYTHON) main_filter.py

digest:
	$(PYTHON) main_digest.py

inspect:
	$(PYTHON) scratch_inspect.py

filter-test:
	$(PYTHON) scratch_filter_test.py

calibrate:
	$(PYTHON) scratch_llm_calibrate.py

llm-server-start:
	$(PYTHON) -m utils.llm_server_ctl start

llm-server-status:
	$(PYTHON) -m utils.llm_server_ctl status

llm-server-stop:
	$(PYTHON) -m utils.llm_server_ctl stop

clean:
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete
