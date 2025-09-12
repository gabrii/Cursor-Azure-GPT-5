# ================================== BUILDER ===================================
ARG INSTALL_PYTHON_VERSION=${INSTALL_PYTHON_VERSION:-PYTHON_VERSION_NOT_SET}

FROM python:${INSTALL_PYTHON_VERSION}-slim-bullseye AS builder

WORKDIR /app

COPY requirements requirements
RUN pip install --no-cache -r requirements/prod.txt

COPY autoapp.py ./
COPY componses componses
COPY .env.example .env

# ================================= PRODUCTION =================================
FROM python:${INSTALL_PYTHON_VERSION}-slim-bullseye as production

WORKDIR /app

RUN useradd -m sid
RUN chown -R sid:sid /app
USER sid
ENV PATH="/home/sid/.local/bin:${PATH}"

COPY requirements requirements
RUN pip install --no-cache --user -r requirements/prod.txt

COPY supervisord/supervisord.conf /etc/supervisor/supervisord.conf
COPY supervisord/gunicorn.conf /etc/supervisor/conf.d/gunicorn.conf

COPY . .

EXPOSE 5000
ENTRYPOINT ["/bin/bash", "supervisord/supervisord_entrypoint.sh"]
CMD ["-c", "/etc/supervisor/supervisord.conf"]


# ================================= DEVELOPMENT ================================
FROM builder AS development
RUN pip install --no-cache -r requirements/dev.txt
EXPOSE 5000
CMD [ "flask", "run", "--host=0.0.0.0" ]
