FROM python:3.8

RUN mkdir /domino-export /domino-export/app /domino-export/instance
COPY ./requirements.txt /domino-export/
RUN cd /domino-export && \
    pip install --no-cache -r requirements.txt

COPY ./run.py ./domino.py /domino-export/
COPY ./app.sh /app.sh
COPY ./app /domino-export/app/

RUN chmod +x /app.sh

ENTRYPOINT ["/app.sh", "/domino-export"]
