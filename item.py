from functools import reduce
import json
import os
import pickle
import re
import requests
import time
from unidecode import unidecode
from urllib.parse import urlparse
from warnings import warn

from bs4 import BeautifulSoup
import pandas as pd


class Item:
    """
    Attributes:
        reference_id (str)
        part_number (str)
        canonical_url (str)
        image_url (str)
        name (str)
        color (str)
        description (str)
        dimensions (str)
        composition (dict)
        care (str)
        category ((audience_segment, type))
        price_history (pd.DataFrame((timestamp, price)))
        availability (pd.DataFrame((timestamp, location, size, available)))
        bought (bool)
        ignore (bool)
        filename (str)
        price_filename (str)
        availability_filename (str)
    """

    PRICE_HISTORY_COLUMNS = ['timestamp', 'price']
    AVAILABILITY_COLUMNS = ['timestamp', 'location', 'size', 'available']
    STORE_AVAILABILITY_URL = (
        'https://itxrest.inditex.com/LOMOServiciosRESTCommerce-ws/'
        'common/1/stock/campaign/V{year}/product/part-number/'
        '{part_number}?physicalStoreId={store_ids}&ajax=true'
    )

    def __init__(self, **kwargs):
        assert 'canonical_url' in kwargs, 'item url not provided'
        self.__dict__.update(kwargs)

    def to_disk(self):
        self.filepath = 'items/{audience_segment}/{type}'.format(
            audience_segment=self.category[0].lower(),
            type=self.category[1].lower()
        )
        os.makedirs(self.filepath, exist_ok=True)
        self.filename = unidecode(
            self.name.lower().replace(' ', '_')
        ) + '.json'
        if self.filename in os.listdir(self.filepath):
            self.filename = (
                self.filename[:-5] +
                '_{time}'.format(time=int(time.time())) +
                self.filename[-5:]
            )
        self.price_filename = 'price_' + self.filename[:-5] + '.csv'
        self.availability_filename = (
            'availability_' + self.filename[:-5] + '.csv'
        )
        if self.ignore:
            self.filename = 'ignore_' + self.filename
            self.price_filename = 'ignore_' + self.price_filename
            self.availability_filename = (
                'ignore_' + self.availability_filename
            )
        if self.bought:
            self.filename = 'bought_' + self.filename
            self.price_filename = 'bought_' + self.price_filename
            self.availability_filename = (
                'bought_' + self.availability_filename
            )

        to_archive = self.__dict__.copy()
        to_archive.pop('price_history')\
                  .to_csv(
                      self.filepath + '/' + self.price_filename, index=False
                  )
        to_archive.pop('availability')\
                  .to_csv(
                      self.filepath + '/' + self.availability_filename,
                      index=False
                  )
        with open(self.filepath + '/' + self.filename, 'w') as f:
            print(json.dumps(to_archive), file=f)

    @staticmethod
    def from_disk(filepath, filename):
        with open(filepath + '/' + filename + '.json', 'r') as f:
            item = Item(**json.load(f))
        item.price_history = pd.read_csv(
            filepath + '/price_' + filename + '.csv'
        )
        item.availability = pd.read_csv(
            filepath + '/availability_' + filename + '.csv'
        )
        return item

    @staticmethod
    def get_soup(url):
        response = requests.get(url)
        return BeautifulSoup(response.text)

    @staticmethod
    def get_data_layer(soup):
        return json.loads(re.match(
            r'.*window\.zara\.dataLayer = (\{.*\});.*',
            [
                script
                for script in soup.find_all(
                    'script', {'type': 'text/javascript'}
                )
                if 'window.zara.appConfig' in script.text
            ][0].text
        ).group(1))

    @staticmethod
    def get_reference_id(soup):
        return soup.find(class_='reference').text

    @staticmethod
    def get_part_number(soup):
        return re.search(
            r'"zara:///1/products\?partNumber=(\d+)"',
            soup.text
        ).groups(1)[0]

    @staticmethod
    def get_canonical_url(soup):
        return soup.find('link', {'rel': 'canonical'})['href']

    @staticmethod
    def get_image_url(soup):
        return urlparse(
            soup.find(class_='_seoImg')['href']
        )._replace(scheme='https', query='').geturl()

    @staticmethod
    def get_name(soup):
        return soup.find('h1', {'class': 'product-name'}).contents[0]

    @staticmethod
    def get_color(soup):
        return soup.find(class_='_colorName').text

    @staticmethod
    def get_description(soup):
        return soup.find(class_='description').text

    @staticmethod
    def get_composition(data_layer):
        return data_layer['product']['detail']['detailedComposition']

    @staticmethod
    def get_composition_str(composition_dict):
        if len(composition_dict.keys() - {'exceptions', 'parts'}) > 0:
            warn('Unexpected field / type encountered in composition.')
        if len({
                type(exception)
                for exception in composition_dict['exceptions']
        } - {str}) > 0:
            warn('Unexpected field / type encountered in composition.')
        if len(
                reduce(
                    lambda a, b: a | b,
                    (part.keys() for part in composition_dict['parts'])
                ) -
                {
                    'areas',
                    'components',
                    'description',
                    'microcontents',
                    'reinforcements'
                }
        ) > 0:
            warn('Unexpected field / type encountered in composition.')
        if len(
                reduce(
                    lambda a, b: a | b,
                    (
                        area.keys()
                        for part in composition_dict['parts']
                        for area in part['areas']
                    )
                ) - {
                    'components', 'description'
                }
        ) > 0:
            warn('Unexpected field / type encountered in composition.')
        if len(
                reduce(
                    lambda a, b: a | b,
                    (
                        component.keys()
                        for part in composition_dict['parts']
                        for component in part['components']
                    )
                ) - {
                    'material', 'percentage'
                }
        ) > 0:
            warn('Unexpected field / type encountered in composition.')
        if len(
                reduce(
                    lambda a, b: a | b,
                    (
                        {
                            type(microcontent)
                            for microcontent in part['microcontents']
                        } | {
                            type(reinforcement)
                            for reinforcement in part['reinforcements']
                        } | {
                            type(part['description'])
                        }
                        for part in composition_dict['parts']
                    )
                ) - {str}
        ) > 0:
            warn('Unexpected field / type encountered in composition.')
        composition_str = ''
        for part in composition_dict['parts']:
            composition_str += part['description'] + '\n'
            for component in part['components']:
                composition_str += (
                    '\t' +
                    component['percentage'] +
                    ' ' +
                    component['material'] +
                    '\n'
                )
            for area in part['areas']:
                composition_str += '\t' + area['description'] + '\n'
                for component in area['components']:
                    composition_str += (
                        '\t\t' +
                        component['percentage'] +
                        ' ' +
                        component['material'] +
                        '\n'
                    )
            if len(part['microcontents']) > 0:
                composition_str += '\t' + 'MICROCONTENTS' + '\n'
                for microcontent in part['microcontents']:
                    composition_str += '\t\t' + microcontent + '\n'
            if len(part['reinforcements']) > 0:
                composition_str += '\t' + 'REINFORCEMENTS' + '\n'
                for reinforcement in part['reinforcements']:
                    composition_str += '\t\t' + reinforcement + '\n'
        if len(composition_dict['exceptions']) > 0:
            composition_str += 'EXCEPTIONS' + '\n'
            for exception in composition_dict['exceptions']:
                composition_str += '\t' + exception + '\n'

        return composition_str

    @staticmethod
    def get_care(data_layer):
        return data_layer['product']['detail']['care']

    @staticmethod
    def get_care_str(care_dict):
        return '. '.join([
            instruction['description']
            for instruction in care_dict
        ]) + '.'

    @staticmethod
    def get_category(soup):
        breadcrumbs = soup.find('div', class_='breadcrumbs')\
                          .find('ul')\
                          .contents
        return (
            breadcrumbs[1].find('a').text,
            breadcrumbs[2].find('a').text
        )

    @staticmethod
    def get_price(data_layer):
        prices = {
            size_info['price']
            for size_info in data_layer['productMetaData']
        }
        assert len(prices) == 1, 'more than one price found for this item'
        return float(prices.pop())

    @staticmethod
    def price_to_DataFrame(timestamp, price):
        return pd.DataFrame(
            [[timestamp, price]],
            columns=Item.PRICE_HISTORY_COLUMNS
        )

    @staticmethod
    def get_size_availabilities(soup):
        return {
            size_tag['value']: size_tag.get('disabled') is None
            for size_tag in soup.find(class_='size-list').find_all('input')
        }

    @staticmethod
    def availability_to_DataFrame(timestamp, size_availabilities):
        return pd.DataFrame(
            [
                [timestamp, 'online', size, available]
                for size, available in size_availabilities.items()
            ],
            columns=Item.AVAILABILITY_COLUMNS
        )

    @staticmethod
    def from_url(url):
        now = int(time.time())
        soup = Item.get_soup(url)
        data_layer = Item.get_data_layer(soup)
        item = Item(
            reference_id=Item.get_reference_id(soup),
            part_number=Item.get_part_number(soup),
            canonical_url=Item.get_canonical_url(soup),
            image_url=Item.get_image_url(soup),
            name=Item.get_name(soup),
            color=Item.get_color(soup),
            description=Item.get_description(soup),
            dimensions=None,
            composition=Item.get_composition(data_layer),
            care=Item.get_care(data_layer),
            category=Item.get_category(soup),
            price_history=Item.price_to_DataFrame(
                now, Item.get_price(data_layer)
            ),
            availability=Item.availability_to_DataFrame(
                now, Item.get_size_availabilities(soup)
            ),
            bought=False,
            ignore=False
        )
        item.to_disk()
        return item

    def update(self, in_memory_update=True, on_disk_update=True):
        now = int(time.time())
        soup = self.get_soup(self.canonical_url)
        data_layer = self.get_data_layer(soup)
        price = self.get_price(data_layer)
        size_availabilities = self.get_size_availabilities(soup)
        if in_memory_update is True:
            self.price_history = pd.concat((
                self.price_history,
                self.price_to_DataFrame(now, price)
            ), axis=1)
            self.availability = pd.concat((
                self.availability,
                self.availability_to_DataFrame(now, size_availabilities)
            ), axis=1)
        if on_disk_update is True:
            with open(self.filepath + '/' + self.price_filename, 'a') as f:
                print(str(now) + ',' + str(float(price)), file=f)
            with open(
                    self.filepath + '/' + self.availability_filename, 'a'
            ) as f:
                print('\n'.join([
                    ','.join([str(now), 'online', str(size), str(available)])
                    for size, available in size_availabilities.items()
                ]), file=f)