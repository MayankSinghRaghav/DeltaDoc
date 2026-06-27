# Apify Actor image (PRD §10, agent #3). Official Apify Python base.
FROM apify/actor-python:3.12

COPY pyproject.toml ./
RUN pip install --no-cache-dir . \
    && pip show deltadocs > /dev/null

COPY . ./

# `python -m deltadocs` runs src/deltadocs/__main__.py -> the Actor entry.
CMD ["python", "-m", "deltadocs"]
