FROM python:3.8
LABEL org.opencontainers.image.source https://github.com/openzim/libretexts-sushi-chef

RUN mkdir -p /app
RUN wget https://github.com/mathjax/MathJax/archive/2.7.6.tar.gz && tar xf 2.7.6.tar.gz && mv MathJax-2.7.6 MathJax
COPY requirements.txt /app/
RUN pip3 install -r /app/requirements.txt
RUN pip3 install -U numpy
COPY *.py /app/
RUN printf "#!/bin/bash\ncd /app && python ./sushichef.py \$@\n" > /usr/local/bin/chef && chmod +x /usr/local/bin/chef

CMD ["chef", "-h"]
