FROM ubuntu:20.04

# set timezone
ENV TZ=Europe/Zurich
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN apt-get update && \
    apt-get --yes install \
        python3 \
        python3-pip \
        libgdal-dev \
        libpq-dev \
        gdal-bin \
        && \
    rm -rf /var/cache/apt/archives/

ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal

COPY cm/heatlearn/requirements.txt requirements.txt
RUN pip3 install -r requirements.txt
COPY cm/base /tmp/base
RUN cd /tmp/base && pip3 install . && python3 test.py
COPY cm/heatlearn .
RUN mkdir -p tmp
RUN python3 test.py
CMD ["python3", "worker.py"]
