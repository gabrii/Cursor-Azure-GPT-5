# Componses

Adapter to use the Responses API through the older Completions API interface. Allows using reasoning models suchas GPT-5 with applications that only support the old completions interface.

## Docker Quickstart

This app can be run completely using `Docker` and `docker compose`. Using Docker is recommended, as it guarantees the application is run using compatible versions of Python.

To run the development version of the app

```bash
docker compose up flask-dev
```

To run the production version of the app

```bash
docker compose up flask-prod
```

The list of `environment:` variables in the `docker compose.yml` file takes precedence over any variables specified in `.env`.

### Running locally

Run the following commands to bootstrap your environment if you are unable to run the application using Docker

```bash
cd componses
pip install -r requirements/dev.txt
flask run --host=0.0.0.0
```

Go to `http://localhost:5000`.

## Deployment

When using Docker, reasonable production defaults are set in `docker compose.yml`

```text
FLASK_ENV=production
FLASK_DEBUG=0
```

Therefore, starting the app in "production" mode is as simple as

```bash
docker compose up flask-prod
```

If running without Docker

```bash
export FLASK_ENV=production
export FLASK_DEBUG=0
flask run       # start the flask server
```

## Running Tests/Linter

To run all tests, run

```bash
docker compose run --rm manage test
flask test # If running locally without Docker
```

To run the linter, run

```bash
docker compose run --rm manage lint
flask lint # If running locally without Docker
```

The `lint` command will attempt to fix any linting/style errors in the code. If you only want to know if the code will pass CI and do not wish for the linter to make changes, add the `--check` argument.
