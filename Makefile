docker:
	docker build -t mrq_local .

test: docker
	sh -c "docker run --rm -i -t -p 27017:27017 -p 6379:6379 -p 5555:5555 -p 20020:20020 -v `pwd`:/app:rw -w /app mrq_local python -m pytest tests/ -v --instafail"

test3: docker
	sh -c "docker run --rm -i -t -p 27017:27017 -p 6379:6379 -p 5555:5555 -p 20020:20020 -v `pwd`:/app:rw -w /app mrq_local python3 -m pytest tests/ -v --instafail"

shell:
	sh -c "docker run --rm -i -t -p 27017:27017 -p 6379:6379 -p 5555:5555 -p 20020:20020 -p 8000:8000 -v `pwd`:/app:rw -w /app mrq_local bash"

shell_noport:
	sh -c "docker run --rm -i -t -v `pwd`:/app:rw -w /app mrq_local bash"

docs_serve:
	sh -c "docker run --rm -i -t-p 8000:8000 -v `pwd`:/app:rw -w /app mrq_local mkdocs serve"

lint: docker
	docker run -i -t -v `pwd`:/app:rw -w /app mrq_local pylint --init-hook="import sys; sys.path.append('.')" --rcfile .pylintrc mrq

linterrors: docker
	docker run -i -t -v `pwd`:/app:rw -w /app mrq_local pylint --errors-only --init-hook="import sys; sys.path.append('.')" -d E1103 --rcfile .pylintrc mrq

linterrors3: docker
	docker run -i -t -v `pwd`:/app:rw -w /app mrq_local python3 -m pylint --errors-only --init-hook="import sys; sys.path.append('.')" -d E1103 --rcfile .pylintrc mrq

virtualenv:
	virtualenv venv --distribute

virtualenv_pypy:
	virtualenv -p /usr/bin/pypy pypy --distribute

deps:
	pip install -r requirements/prod.txt.txt
	pip install -r requirements/dev.txt
	pip install -r requirements/dashboard.txt

deps_pypy:
	pip install git+git://github.com/schmir/gevent@pypy-hacks
	pip install cffi
	pip install git+git://github.com/gevent-on-pypy/pypycore
	export GEVENT_LOOP=pypycore.loop
	pip install -r requirements/pypy.txt

clean:
	find . -path ./venv -prune -o -name "*.pyc" -exec rm {} \;
	find . -name __pycache__ | xargs rm -r

dashboard:
	python mrq/dashboard/app.py

stack:
	mongod --smallfiles --noprealloc --nojournal &
	redis-server &
	python mrq/dashboard/app.py &

pep8:
	autopep8 --max-line-length 99 -aaaaaaaa --diff --recursive mrq
	echo "Now run 'make autopep8' to apply."

autopep8:
	autopep8 --max-line-length 99 -aaaaaaaa --in-place --recursive mrq

pypi: linterrors
	python setup.py sdist upload

build_docs:
	python scripts/propagate_docs.py
