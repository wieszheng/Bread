# --------- requirements ---------
FROM python:3.12-slim As builder
WORKDIR /bread
COPY ./requirements.txt .

RUN python -m venv /bread/venv \
    && /bread/venv/bin/pip install --no-cache-dir --upgrade -r requirements.txt

RUN apt update -y \
    && apt install -y tzdata wget vim \
    && apt clean


# --------- final image build ---------
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /bread
COPY . .
COPY --from=builder /bread/venv/ /bread/venv/
COPY --from=builder /usr/share/zoneinfo/Asia/Shanghai /etc/localtime

EXPOSE 9099
CMD ["/bread/venv/bin/supervisord", "-c", "/bread/supervisord.conf"]