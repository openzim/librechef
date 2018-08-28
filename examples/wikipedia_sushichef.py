#!/usr/bin/env python

import os
import sys;
sys.path.append(os.getcwd()) # Handle relative imports
from ricecooker.utils import downloader, html_writer
from ricecooker.chefs import SushiChef
from ricecooker.classes import nodes, files
from ricecooker.config import LOGGER                        # Use logger to print messages
from ricecooker.exceptions import raise_for_invalid_channel

""" Additional imports """
###########################################################
import requests
import tempfile
import logging
from le_utils.constants import licenses, file_formats
from bs4 import BeautifulSoup
from selenium import webdriver
from ricecooker.utils.html import download_file
from ricecooker.utils.zip import create_predictable_zip


""" Run Constants"""
###########################################################

CHANNEL_NAME = "Example Wikipedia"                          # Name of channel
CHANNEL_SOURCE_ID = "sushichef-example-mara80@gmail.com" # Channel's unique id
CHANNEL_DOMAIN = "en.wikipedia.org"                         # Who is providing the content
CHANNEL_LANGUAGE = "en"                                     # Language of channel
CHANNEL_DESCRIPTION = None                                  # Description of the channel (optional)
CHANNEL_THUMBNAIL = 'https://vignette2.wikia.nocookie.net/uncyclopedia/images/6/63/Wikipedia-logo.png' # Local path or url to image file (optional)


""" Additional Constants """
###########################################################
BASE_URL = 'https://en.wikipedia.org/wiki'

# License to be used for content under channel
CHANNEL_LICENSE = licenses.PUBLIC_DOMAIN


""" The chef class that takes care of uploading channel to the content curation server. """
class WikipediaChef(SushiChef):

    channel_info = {                                   # Channel Metadata
        'CHANNEL_SOURCE_DOMAIN': CHANNEL_DOMAIN,       # Who is providing the content
        'CHANNEL_SOURCE_ID': CHANNEL_SOURCE_ID,        # Channel's unique id
        'CHANNEL_TITLE': CHANNEL_NAME,                 # Name of channel
        'CHANNEL_LANGUAGE': CHANNEL_LANGUAGE,          # Language of channel
        'CHANNEL_THUMBNAIL': CHANNEL_THUMBNAIL,        # Local path or url to image file (optional)
        'CHANNEL_DESCRIPTION': CHANNEL_DESCRIPTION,    # Description of the channel (optional)
    }

    """ Main scraping method """
    ###########################################################

    def construct_channel(self, *args, **kwargs):
        """ construct_channel: Creates ChannelNode and build topic tree

            Wikipedia is organized with the following hierarchy:
                Citrus (Folder)
                |   Citrus Page HTML Zip (File)
                Potatoes (Folder)
                |   Potatoes Page HTML Zip (File)

            Returns: ChannelNode
        """
        LOGGER.info("Constructing channel from {}...".format(BASE_URL))

        channel = self.get_channel(*args, **kwargs)                         # Creates ChannelNode from data in self.channel_info

        create_topic(channel, "Citrus!", "List_of_citrus_fruits")       # Add Citrus folder
        create_topic(channel, "Potatoes!", "List_of_potato_cultivars")  # Add Potatoes folder

        raise_for_invalid_channel(channel)                                  # Check for errors in channel construction

        return channel


""" Helper Methods """
###########################################################

def create_topic(channel, title, endpoint):
    """ Write folder to zip and download pages """
    LOGGER.info('   Writing {} Folder...'.format(title))
    topic = nodes.TopicNode(source_id=endpoint, title=title)
    channel.add_child(topic)
    add_subpages_from_wikipedia_list(topic, '{}/{}'.format(BASE_URL, endpoint))

def make_fully_qualified_url(url):
    """ Ensure url is qualified """
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return "https://en.wikipedia.org" + url
    assert url.startswith("http"), "Bad URL (relative to unknown location): " + url
    return url

def read_source(url):
    """ Read page source as beautiful soup """
    html = downloader.read(url)
    return BeautifulSoup(html, "html.parser")

def download_wikipedia_page(url, thumbnail, title):
    """ Create zip file to use for html pages """
    destpath = tempfile.mkdtemp()   # Create a temp directory to house our downloaded files

    # downlod the main wikipedia page, apply a middleware processor, and call it index.html
    localref, _ = download_file(
        url,
        destpath,
        filename="index.html",
        middleware_callbacks=process_wikipedia_page,
    )

    zippath = create_predictable_zip(destpath)  # Turn the temp folder into a zip file

    # Create an HTML5 app node
    html5app = nodes.HTML5AppNode(
        files=[files.HTMLZipFile(zippath)],
        title=title,
        thumbnail=thumbnail,
        source_id=url.split("/")[-1],
        license=CHANNEL_LICENSE,
    )

    return html5app

def process_wikipedia_page(content, baseurl, destpath, **kwargs):
    """ Saves images to html zip folder """
    page = BeautifulSoup(content, "html.parser")

    # Add style sheets to zip file
    index = 0
    for link in page.find_all("link"):
        if link.get('href') and link['href'].startswith('/'): # Import relative links
            try:
                subpath = "item_{}".format(index)
                link["href"], _ = download_file(make_fully_qualified_url(link['href']), destpath, subpath=subpath)
                index = index + 1
            except Exception:
                link["href"] = "#"

    # Add images to zip file
    for image in page.find_all("img"):
        try:
            relpath, _ = download_file(make_fully_qualified_url(image["src"]), destpath)
            image["src"] = relpath
        except Exception:
            image["src"] = "#"

    # Replace links with text to avoid broken links
    content = str(page)
    for link in page.find_all("a"):
        if link.get('href') and not link['href'].startswith("#"):
            content = content.replace(str(link), link.text)

    return content

def add_subpages_from_wikipedia_list(topic, list_url):
    """ add_subpages_from_wikipedia_list: Parses wiki pages and creates corresponding files
        To understand how the following parsing works, look at:
            1. the source of the page (e.g. https://en.wikipedia.org/wiki/List_of_citrus_fruits), or inspect in chrome dev tools
            2. the documentation for BeautifulSoup version 4: https://www.crummy.com/software/BeautifulSoup/bs4/doc/
    """
    page = read_source(list_url)        # Parse the the page into BeautifulSoup format, so we can loop through and manipulate it
    table = page.find("table")          # Extract the main table from the page

    # Loop through all the rows in the table
    for row in table.find_all("tr"):
        columns = row.find_all("td")    # Extract the columns (cells, really) within the current row
        if not columns:                 # Some rows are empty, so just skip
            continue

        link = columns[0].find("a")     # Get the link to the subpage
        if not link:                    # Some rows don't have links, so skip
            continue

        # Extract the URL and title for the subpage
        url = make_fully_qualified_url(link["href"])
        title = link.text
        LOGGER.info("      Writing {}...".format(title))

        # Attempt to extract a thumbnail for the subpage, from the second column in the table
        image = columns[1].find("img")
        thumbnail_url = make_fully_qualified_url(image["src"]) if image else None
        if thumbnail_url and not (thumbnail_url.endswith("jpg") or thumbnail_url.endswith("png")):
            thumbnail_url = None

        # Download the wikipedia page into an HTML5 app node
        html5app = download_wikipedia_page(url, thumbnail=thumbnail_url, title=title)

        # Add the downloaded HTML5 app node into the topic
        topic.add_child(html5app)


""" This code will run when the sushi chef is called from the command line. """
if __name__ == '__main__':

    wikichef = WikipediaChef()
    wikichef.main()
