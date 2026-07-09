import csv
import os
import logging

import requests

logger = logging.getLogger(__name__)


def get_quotation(verbose, dryrun):
    endpoint = os.environ['QUOTATION_API_ENDPOINT']
    response = requests.get(endpoint)

    if response.status_code // 100 != 2:
        raise Exception(f'Error calling api, response status code {response.status_code}')

    logger.debug(f'Endpoint "{endpoint}" answered with status code {response.status_code}')

    return response.json()


def read_csv(filepath):
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        return list(reader)
