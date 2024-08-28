# --------- requirements ---------

FROM python:3.12-slim as requirements-stage
WORKDIR /bread
COPY ./requirements.txt .

RUN apt update -y \
    && apt install -y tzdata wget \
    && apt clean \

RUN python -m venv /bread/venv \
    && /bread/venv/bin/pip install --no-cache-dir --upgrade -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple

# --------- final image build ---------

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /bread
COPY . .
COPY --from=requirements-stage /bread/venv/ /bread/venv/
COPY --from=requirements-stage /usr/share/zoneinfo/Asia/Shanghai /etc/localtime

EXPOSE 5021
CMD ["/bread/venv/bin/supervisord", "-c", "/bread/supervisord.conf"]