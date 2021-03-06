APP_ENV = development
DATABASE_URL?=postgresql://postgres@localhost:5432/ooni_measurements
VERSION = $(shell cat package.json \
  | grep version \
  | head -1 \
  | awk -F: '{ print $$2 }' \
  | sed 's/[",]//g' \
  | tr -d '[[:space:]]')

PWD = $(shell pwd)

PYTHON_WITH_ENV = PYTHONPATH=$(PWD) APP_ENV=$(APP_ENV) DATABASE_URL=$(DATABASE_URL) python

-include make.conf # to override DATABASE_URL, PYTHON_WITH_ENV to use venv and so on

default:
	@echo "ERR: Did not specify a command"
	@exit 1

clean:
	rm -rf measurements/static/dist venv

venv:
	virtualenv -p python3.7 venv && venv/bin/pip install -r requirements/deploy.txt -r requirements/main.txt -r requirements/tests.txt

tox37:
	tox -e py37 $(args)

tox37-coverage:
	tox -e py37 -- --cov --cov-report=term-missing $(args)

dev:
	$(PYTHON_WITH_ENV) -m measurements run -p 3000 --reload

update-country-list:
	curl https://raw.githubusercontent.com/hellais/country-util/master/data/country-list.json > measurements/countries/country-list.json

shell:
	$(PYTHON_WITH_ENV) -m measurements shell

test-unit:
	$(PYTHON_WITH_ENV) -m coverage run -m pytest -m unit

test-functional:
	$(PYTHON_WITH_ENV) -m coverage run -m pytest -m functional

test: test-unit test-functional
	$(PYTHON_WITH_ENV) -m coverage report -m

.PHONY: default dev build clean shell \
		test test-unit test-functional
