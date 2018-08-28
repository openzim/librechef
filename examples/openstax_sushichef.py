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
import logging
import json
from le_utils.constants import licenses, file_formats
from bs4 import BeautifulSoup
from selenium import webdriver


""" Run Constants"""
###########################################################

CHANNEL_NAME = "Example Open Stax"      # Name of channel
CHANNEL_SOURCE_ID = "sushichef-example-mara80@gmail.com" # Channel's unique id
CHANNEL_DOMAIN = "openstax.org"         # Who is providing the content
CHANNEL_LANGUAGE = "en"                 # Language of channel
CHANNEL_DESCRIPTION = None              # Description of the channel (optional)
CHANNEL_THUMBNAIL = "https://pbs.twimg.com/profile_images/461533721493897216/Q-kxGJ-b_400x400.png" # Local path or url to image file (optional)

""" Additional Constants """
###########################################################

BASE_URL = "https://openstax.org/api"
DOWNLOAD_DIRECTORY = "{}{}{}".format(os.path.dirname(os.path.realpath(__file__)), os.path.sep, "downloads")

# Create download directory if it doesn't already exist
if not os.path.exists(DOWNLOAD_DIRECTORY):
    os.makedirs(DOWNLOAD_DIRECTORY)

# Map for Open Stax licenses to le_utils license constants
LICENSE_MAPPING = {
    "Creative Commons Attribution License": licenses.CC_BY,
    "Creative Commons Attribution-NonCommercial-ShareAlike License": licenses.CC_BY_NC_SA,
}
COPYRIGHT_HOLDER = "Rice University"


""" The chef class that takes care of uploading channel to the content curation server. """
class MyChef(SushiChef):

    channel_info = {                                  # Channel Metadata
        'CHANNEL_SOURCE_DOMAIN': CHANNEL_DOMAIN,      # Who is providing the content
        'CHANNEL_SOURCE_ID': CHANNEL_SOURCE_ID,       # Channel's unique id
        'CHANNEL_TITLE': CHANNEL_NAME,                # Name of channel
        'CHANNEL_LANGUAGE': CHANNEL_LANGUAGE,         # Language of channel
        'CHANNEL_THUMBNAIL': CHANNEL_THUMBNAIL,       # Local path or url to image file (optional)
        'CHANNEL_DESCRIPTION': CHANNEL_DESCRIPTION,   # Description of the channel (optional)
    }

    """ Main scraping method """
    ###########################################################

    def construct_channel(self, *args, **kwargs):
        """ construct_channel: Creates ChannelNode and build topic tree

            OpenStax is organized with the following hierarchy:
                Subject (Topic)
                |   Book (Topic)
                |   |   Main High Resolution PDF (DocumentNode)
                |   |   Main Low Resolution PDF (DocumentNode)
                |   |   Instructor Resources (Topic)
                |   |   |   Resource PDF (DocumentNode)
                |   |   Student Resources (Topic)
                |   |   |   Resource PDF (DocumentNode)

            Returns: ChannelNode
        """
        LOGGER.info("Constructing channel from {}...".format(BASE_URL))

        channel = self.get_channel(*args, **kwargs)             # Creates ChannelNode from data in self.channel_info
        contents = read_source()                                # Get json data from page

        for book in contents.get('books'):
            subject = book.get('subject')

            # Get subject, add if not available
            subject_node = next((child for child in channel.children if child.source_id == subject), None)
            if not subject_node:
                subject_node = nodes.TopicNode(source_id=subject, title=subject)
                channel.add_child(subject_node)

            content = read_source(endpoint=book.get('slug'))     # Read detailed page for content

            if not content:                                      # Skip to next item if nothing is found
                continue

            # Format licensing metadata for content
            auth_info = {
                "license": LICENSE_MAPPING[content.get('license_name')],
                "license_description": content.get('license_text'),
                "copyright_holder": COPYRIGHT_HOLDER,
            }

            # Format content metadata for content
            authors = ", ".join([a['value']['name'] for a in content['authors'][:5]])
            authors = authors + " et. al." if len(content['authors']) > 5 else authors
            details = {
                "description": parse_description(content.get('description')),
                "thumbnail": get_thumbnail(content.get('cover_url')),
                "author": authors,
            }

            # Add book topic
            book_node = nodes.TopicNode(
                source_id=str(content.get('cnx_id')),
                title=content.get('title'),
                author=details.get('author'),
                description=details.get('description'),
                thumbnail=details.get('thumbnail'),
            )
            subject_node.add_child(book_node)

            # Create high resolution document
            LOGGER.info("   Writing {} documents...".format(book.get('title')))
            highres_title = "{} ({} Resolution)".format(content['title'], "High")
            add_file_node(book_node, content.get("high_resolution_pdf_url"), highres_title, **auth_info, **details)

            # Create low resolution document
            lowres_title = "{} ({} Resolution)".format(content['title'], "Low")
            add_file_node(book_node, content.get("low_resolution_pdf_url"), lowres_title, **auth_info, **details)

            # Create student handbook document
            add_file_node(book_node, content.get("student_handbook_url"), "Student Handbook", **auth_info, **details)

            # Parse resource materials
            LOGGER.info("   Writing {} resources...".format(book.get('title')))
            parse_resources("Instructor Resources", content.get('book_faculty_resources'), book_node, **auth_info)
            parse_resources("Student Resources", content.get('book_student_resources'), book_node, **auth_info)

        raise_for_invalid_channel(channel)                           # Check for errors in channel construction

        return channel


""" Helper Methods """
###########################################################

def read_source(endpoint="books"):
    """ Reads page source using downloader class to get json data """
    page_contents = downloader.read("{baseurl}/{endpoint}".format(baseurl=BASE_URL, endpoint=endpoint))
    return json.loads(page_contents) # Open Stax url returns json object

def get_thumbnail(url):
    """ Reads page source using downloader class to get json data """
    # Hacky method to get images, but much more lightweight than converting svg to png
    filename, _ext = os.path.splitext(os.path.basename(url))
    img_path = "{}{}{}.png".format(DOWNLOAD_DIRECTORY, os.path.sep, filename)
    driver = webdriver.PhantomJS()
    driver.set_script_timeout(30)
    driver.get(url)
    driver.save_screenshot(img_path)
    return files.ThumbnailFile(path=img_path)

def parse_description(description):
    """ Removes html tags from description """
    return BeautifulSoup(description or "", "html5lib").text

def add_file_node(target_node, url, title, **details):
    """ Creates file node at target topic node """
    document_file = files.DocumentFile(path=url)
    document_id = title.replace(" ", "-").lower()
    document_node = nodes.DocumentNode(
        source_id="{}-{}".format(target_node.source_id, document_id),
        title=title,
        files=[document_file],
        **details
    )
    target_node.add_child(document_node)

def parse_resources(resource_name, resource_data, book_node, **auth_info):
    """ Creates resource topics """
    resource_data = resource_data or []
    resource_str = "{}-{}".format(book_node.source_id, resource_name.replace(' ', '-').lower())

    # Create resource topic
    resource_node = nodes.TopicNode(source_id=resource_str, title=resource_name)
    book_node.add_child(resource_node)

    # Add resource documents
    for resource in resource_data:
        if resource.get('link_document_url') and resource['link_document_url'].endswith(".pdf"):
            description = parse_description(resource.get('resource_description'))
            add_file_node(resource_node, resource.get("link_document_url"), resource.get('resource_heading'), description=description, **auth_info)


""" This code will run when the sushi chef is called from the command line. """
if __name__ == '__main__':

    chef = MyChef()
    chef.main()
