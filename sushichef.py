#!/usr/bin/env python

from bs4 import BeautifulSoup
import codecs
from collections import defaultdict, OrderedDict
import copy
from git import Repo
import glob
from le_utils.constants import licenses, content_kinds, file_formats
import hashlib
import json
import logging
import markdown2
import ntpath
import os
from pathlib import Path
import re
import requests
from ricecooker.classes.licenses import get_license
from ricecooker.chefs import JsonTreeChef
from ricecooker.utils import downloader, html_writer
from ricecooker.utils.caching import CacheForeverHeuristic, FileCache, CacheControlAdapter
from ricecooker.utils.jsontrees import write_tree_to_json_tree, SUBTITLES_FILE
import time
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.parse import urlparse, parse_qs 
from utils import if_dir_exists, get_name_from_url, clone_repo, build_path
from utils import if_file_exists, get_video_resolution_format, remove_links
from utils import get_name_from_url_no_ext, get_node_from_channel, get_level_map
from utils import remove_iframes, get_confirm_token, save_response_content
from utils import link_to_text, remove_scripts
import youtube_dl


BASE_URL = "https://phys.libretexts.org/"

DATA_DIR = "chefdata"
COPYRIGHT_HOLDER = "CSU and Merlot"
LICENSE = get_license(licenses.CC_BY_NC_SA, 
        copyright_holder=COPYRIGHT_HOLDER).as_dict()
AUTHOR = "CSU and Merlot"

LOGGER = logging.getLogger()
__logging_handler = logging.StreamHandler()
LOGGER.addHandler(__logging_handler)
LOGGER.setLevel(logging.INFO)

DOWNLOAD_VIDEOS = True

sess = requests.Session()
cache = FileCache('.webcache')
basic_adapter = CacheControlAdapter(cache=cache)
forever_adapter = CacheControlAdapter(heuristic=CacheForeverHeuristic(), cache=cache)
sess.mount('http://', basic_adapter)
sess.mount(BASE_URL, forever_adapter)

# Run constants
################################################################################
CHANNEL_NAME = "Libretext Open Educational Resource Library"              # Name of channel
CHANNEL_SOURCE_ID = "sushi-chef-phys-libretext"    # Channel's unique id
CHANNEL_DOMAIN = "https://phys.libretexts.org/"          # Who is providing the content
CHANNEL_LANGUAGE = "en"      # Language of channel
CHANNEL_DESCRIPTION = None                                  # Description of the channel (optional)
CHANNEL_THUMBNAIL = None                                    # Local path or url to image file (optional)

# Additional constants
################################################################################

class Browser:
    def __init__(self, url):
        self.url = url

    def run(self, from_i=1, to_i=None):
        document = download(self.url)
        if document is not None:
            soup = BeautifulSoup(document, 'html5lib') #html.parser
        section = soup.find("section", class_="mt-content-container")
        section_div = section.find("div", class_="noindex")
        for tag_a in section_div.find_all("a"):
            yield tag_a


class LinkCollection:
    def __init__(self, links):
        self.links = links
        self.to_collection()

    def to_collection(self):
        self.collection = []
        for link in self.links:
            self.collection.append(Collection(link.text, link.attrs.get("href", "")))
        
    def to_node(self):
        for collection in self.collection:
            yield collection.to_node()


class Collection:
    def __init__(self, title, link):
        self.title = title
        self.source_id = link
        self.collection = {
            CourseLibreTexts.title: CourseLibreTexts,
            #TextBooksTextMaps.title: TextBooksTextMaps
        }

    def to_node(self):
        try:
            Course = self.collection[self.title]
        except KeyError:
            print("Not Found", self.title)
        else:
            LOGGER.info(self.title)
            course = Course(Browser(self.source_id).run())
            course.units()
            return course.to_node()


class CourseLibreTexts(object):
    title = "Course LibreTexts"
    def __init__(self, urls):
        self.urls = urls
        self.lang = "en"
        self.tree_nodes = OrderedDict()

    def __iter__(self):
        return self.urls

    def __next__(self):
        return next(self.urls)

    def units(self):
        for url in self:
            for link in Browser(url.attrs.get("href")).run():
                course_index = CourseIndex(link.text, link.attrs.get("href"))
                course_index.description = link.attrs.get("title")
                path = [DATA_DIR, link.text]
                course_index.index(build_path(path))
                self.tree_nodes[course_index.source_id] = course_index.to_node()
                return

    def to_node(self):
        return dict(
            kind=content_kinds.TOPIC,
            source_id=self.title,
            title=self.title,
            description="",
            language=self.lang,
            author="",
            license=LICENSE,
            children=list(self.tree_nodes.values())
        )
            

class CourseIndex(object):
    def __init__(self, title, url):
        self.source_id = url
        self.title = title
        self.lang = "en"
        self.description = None
        self.tree_nodes = OrderedDict()

        document = download(self.source_id)
        if document is not None:
            self.soup = BeautifulSoup(document, 'html5lib') #html5lib
        self.author()

    def author(self):
        div = self.soup.find("div", "mt-author-container")
        if div is not None:
            tag_a = div.find(lambda tag: tag.name == "a" and tag.findParent("li", class_="mt-author-information"))
            return tag_a.text

    def index(self, base_path):
        courses_link = self.soup.find_all(lambda tag: tag.name == "a" and tag.findParent("dt", class_="mt-listing-detailed-title"))
        if len(courses_link) == 0:
            courses_link = self.soup.find_all(lambda tag: tag.name == "a" and tag.findParent("li", class_="mt-sortable-listing"))
        if len(courses_link) == 0:
            query = QueryPage(self.soup)
            body = query.body()
            courses_link = body.find_all("a")

        index_base_path = build_path([base_path])
        for course_link in courses_link:
            LOGGER.info("-- " + course_link.text)
            document = download(course_link.attrs.get("href", ""))
            if document is not None:
                query = QueryPage(BeautifulSoup(document, 'html.parser'))
                course_body = query.body()
                if course_body is not None:
                    chapter_basepath = build_path([index_base_path, course_link.text])
                    for chapter_title in course_body.find_all("a"):
                        LOGGER.info("---- " + chapter_title.text)
                        chapter = Chapter(chapter_title.text, chapter_title.attrs.get("href", ""))
                        video_nodes = chapter.video_nodes(chapter_basepath, chapter.body())
                        chapter.to_file(chapter_basepath)
                        self.tree_nodes[chapter.source_id] = chapter.to_node()
                        for video_node in video_nodes:
                            self.tree_nodes[video_node["source_id"]] = video_node
                        #return

    def to_node(self):
        return dict(
            kind=content_kinds.TOPIC,
            source_id=self.source_id,
            title=self.title,
            description=self.description,
            language=self.lang,
            author=self.author(),
            license=LICENSE,
            children=list(self.tree_nodes.values())
        )


class TextBooksTextMaps(object):
    title = "TextBooks & TextMaps"
    def __init__(self, urls):
        self.urls = urls

    def __iter__(self):
        return self.urls

    def __next__(self):
        return next(self.urls)

    def units(self):
        for url in self:
            for link in Browser(url.attrs.get("href")).run():
                print(link.text)


class Chapter:
    def __init__(self, title, url):
        self.title = title
        self.source_id = url
        self.page = self.to_soup()
        self.lang = "en"
        self.filepath = None

    def to_soup(self):
        document = download(self.source_id)
        if document is not None:
            return BeautifulSoup(document, 'html.parser')

    def body(self):
        return self.page.find("section", class_="mt-content-container")        

    def clean(self, content):
        link_to_text(content)
        remove_links(content)
        remove_iframes(content)
        remove_scripts(content)
        return content

    def mathjax(self):
        scripts = self.page.find_all("script", type="text/x-mathjax-config")
        return "".join([str(s) for s in scripts])

    def mathjax_dependences(self, filepath):
        mathajax_path = "../../MathJax/"
        dependences = [
            "config/TeX-AMS_HTML.js",
            "jax/input/TeX/config.js",
            "jax/input/MathML/config.js",
            "jax/output/SVG/config.js",
            "extensions/tex2jax.js",
            "extensions/mml2jax.js",
            "extensions/MathMenu.js",
            "extensions/MathZoom.js",
            "extensions/TeX/autobold.js",
            "extensions/TeX/mhchem.js",
            "extensions/TeX/color.js", 
            "extensions/TeX/cancel.js",
            "jax/output/HTML-CSS/jax.js",
            "jax/output/HTML-CSS/fonts/TeX/fontdata.js",
            "jax/output/HTML-CSS/autoload/mtable.js"
        ]
        for dep in dependences:
            filename = dep.split("/")[-1]
            dep_path = "/".join(dep.split("/")[:-1])
            dep_file_path = os.path.join(mathajax_path, dep_path, filename)
            with html_writer.HTMLWriter(filepath, "a") as zipper, open(dep_file_path) as f:
                content = f.read()
                zipper.write_contents(filename, content, directory="js/"+dep_path)

    def get_images(self, content):
        images_urls = {}
        for img in content.findAll("img"):
            try:
                img_src = img["src"]
            except KeyError:
                continue
            else:
                if img_src.startswith("/"):
                    img_src = urljoin(BASE_URL, img_src)
                filename = get_name_from_url(img_src)
                if img_src not in images_urls and img_src:
                    img["src"] = filename
                    images_urls[img_src] = filename
        return images_urls

    def video_nodes(self, base_path, content):
        videos_url = self.get_videos_urls(content)
        base_path = build_path([DATA_DIR, "videos"])
        video_nodes = []
        for video_url in videos_url:
            if YouTubeResource.is_youtube(video_url):
                video = YouTubeResource(video_url, lang=self.lang)
                video.download(download=DOWNLOAD_VIDEOS, base_path=base_path)
                video_nodes.append(video.to_node())
        return video_nodes

    def get_videos_urls(self, content):
        urls = set([])
        video_urls = content.find_all(lambda tag: tag.name == "a" and tag.attrs.get("href", "").find("youtube") != -1 or tag.attrs.get("href", "").find("youtu.be") != -1 or tag.text.lower() == "youtube")

        for video_url in video_urls:
            urls.add(video_url.get("href", ""))

        for iframe in content.find_all("iframe"):
            url = iframe["src"]
            if YouTubeResource.is_youtube(url):
                urls.add(YouTubeResource.transform_embed(url))

        return urls

    def write_index(self, filepath, content):
        with html_writer.HTMLWriter(filepath, "w") as zipper:
            zipper.write_index_contents(content)

    def write_images(self, filepath, content):
        images = self.get_images(content)
        with html_writer.HTMLWriter(filepath, "a") as zipper:
            for img_src, img_filename in images.items():
                try:
                    zipper.write_url(img_src, img_filename, directory=".")
                except requests.exceptions.HTTPError:
                    pass

    def write_css_js(self, filepath):
        with html_writer.HTMLWriter(filepath, "a") as zipper, open("chefdata/styles.css") as f:
            content = f.read()
            zipper.write_contents("styles.css", content, directory="css/")

        with html_writer.HTMLWriter(filepath, "a") as zipper, open("chefdata/scripts.js") as f:
            content = f.read()
            zipper.write_contents("scripts.js", content, directory="js/")
        
    def write_mathjax(self, filepath):
        script_tag = self.page.find(lambda tag: tag.name == "script" and tag.attrs.get("src", "").find("MathJax.js") != -1)
        filepath_js = "chefdata/MathJax.js"
        if not if_file_exists(filepath_js) and script_tag:
            try:
                r = requests.get(script_tag["src"])
                with open(filepath_js, "wb") as f:
                    f.write(r.content)
            except KeyError:
                pass

        with html_writer.HTMLWriter(filepath, "a") as zipper, open(filepath_js) as f:
            content = f.read()
            zipper.write_contents("MathJax.js", content, directory="js/")

    def to_file(self, base_path):
        self.filepath = "{path}/{name}.zip".format(path=base_path, name=self.title)
        mathjax_scripts = self.mathjax()
        body = self.clean(self.body())
        self.write_index(self.filepath, '<html><head><meta charset="utf-8"><link rel="stylesheet" href="css/styles.css"></head><body><div class="main-content-with-sidebar">{}</div><script src="js/scripts.js"></script>{}<script src="js/MathJax.js?config=TeX-AMS_HTML"></script></body></html>'.format(body, mathjax_scripts))
        self.write_images(self.filepath, body)
        self.write_css_js(self.filepath)
        self.write_mathjax(self.filepath)
        self.mathjax_dependences(self.filepath)

    def to_node(self):
        return dict(
            kind=content_kinds.HTML5,
            source_id=self.source_id,
            title=self.title,
            description="",
            thumbnail=None,
            author="",
            files=[dict(
                file_type=content_kinds.HTML5,
                path=self.filepath
            )],
            language=self.lang,
            license=LICENSE)


class QueryPage:
    def __init__(self, soup):
        self.soup = soup
        self.get_id()

    def get_id(self):
        query_param = self.soup.find("div", class_="mt-guide-tabs-container")
        if query_param is not None:
            self.page_id = query_param.attrs.get("data-page-id", "")
            query_param = self.soup.find("li", class_="mt-guide-tab")
            self.guid = query_param.attrs.get("data-guid", "")
        else:
            self.page_id = None
            self.guid = None

    def body(self):
        if self.page_id is not None and self.guid is not None:
            url = "{}@api/deki/pages/=Template%253AMindTouch%252FIDF3%252FViews%252FTopic_hierarchy/contents?dream.out.format=json&origin=mt-web&pageid={}&draft=false&guid={}".format(BASE_URL, self.page_id, self.guid)
            json = requests.get(url).json()
            return BeautifulSoup(json["body"], 'html.parser')


class YouTubeResource(object):
    def __init__(self, source_id, name=None, type_name="Youtube", lang="en", 
            embeded=False, section_title=None, description=None):
        LOGGER.info("    + Resource Type: {}".format(type_name))
        LOGGER.info("    - URL: {}".format(source_id))
        self.filename = None
        self.type_name = type_name
        self.filepath = None
        if embeded is True:
            self.source_id = YouTubeResource.transform_embed(source_id)
        else:
            self.source_id = self.clean_url(source_id)
        
        self.name = name
        self.section_title = self.get_name(section_title)
        self.description = description
        self.file_format = file_formats.MP4
        self.lang = lang
        self.is_valid = False

    def clean_url(self, url):
        if url[-1] == "/":
            url = url[:-1]
        return url.strip()

    def get_name(self, name):
        if name is None:
            name = self.source_id.split("/")[-1]
            name = name.split("?")[0]
            return " ".join(name.split("_")).title()
        else:
            return name

    @classmethod
    def is_youtube(self, url, get_channel=False):
        youtube = url.find("youtube") != -1 or url.find("youtu.be") != -1
        if get_channel is False:
            youtube = youtube and url.find("user") == -1 and url.find("/c/") == -1
        return youtube

    @classmethod
    def transform_embed(self, url):
        url = "".join(url.split("?")[:1])
        return url.replace("embed/", "watch?v=").strip()

    def get_video_info(self, download_to=None, subtitles=True):
        ydl_options = {
                'writesubtitles': subtitles,
                'allsubtitles': subtitles,
                'no_warnings': True,
                'restrictfilenames':True,
                'continuedl': True,
                'quiet': False,
                'format': "bestvideo[height<={maxheight}][ext=mp4]+bestaudio[ext=m4a]/best[height<={maxheight}][ext=mp4]".format(maxheight='480'),
                'outtmpl': '{}/%(id)s'.format(download_to),
                'noplaylist': False
            }

        with youtube_dl.YoutubeDL(ydl_options) as ydl:
            try:
                ydl.add_default_info_extractors()
                info = ydl.extract_info(self.source_id, download=(download_to is not None))
                return info
            except(youtube_dl.utils.DownloadError, youtube_dl.utils.ContentTooShortError,
                    youtube_dl.utils.ExtractorError) as e:
                LOGGER.info('An error occured ' + str(e))
                LOGGER.info(self.source_id)
            except KeyError as e:
                LOGGER.info(str(e))

    def subtitles_dict(self):
        subs = []
        video_info = self.get_video_info()
        if video_info is not None:
            video_id = video_info["id"]
            if 'subtitles' in video_info:
                subtitles_info = video_info["subtitles"]
                LOGGER.info("Subtitles: {}".format(",".join(subtitles_info.keys())))
                for language in subtitles_info.keys():
                    subs.append(dict(file_type=SUBTITLES_FILE, youtube_id=video_id, language=language))
        return subs

    def download(self, download=True, base_path=None):
        download_to = build_path([base_path])
        for i in range(4):
            try:
                info = self.get_video_info(download_to=download_to, subtitles=False)
                if info is not None:
                    LOGGER.info("    + Video resolution: {}x{}".format(info.get("width", ""), info.get("height", "")))
                    if self. description is None:
                        self.description = info["description"]
                    self.filepath = os.path.join(download_to, "{}.mp4".format(info["id"]))
                    self.filename = info["title"]
                    if self.filepath is not None and os.stat(self.filepath).st_size == 0:
                        LOGGER.info("    + Empty file")
                        self.filepath = None
            except (ValueError, IOError, OSError, URLError, ConnectionResetError) as e:
                LOGGER.info(e)
                LOGGER.info("Download retry")
                time.sleep(.8)
            except (youtube_dl.utils.DownloadError, youtube_dl.utils.ContentTooShortError,
                    youtube_dl.utils.ExtractorError, OSError) as e:
                LOGGER.info("    + An error ocurred, may be the video is not available.")
                return
            except OSError:
                return
            else:
                return

    def to_node(self):
        if self.filepath is not None:
            files = [dict(file_type=content_kinds.VIDEO, path=self.filepath)]
            files += self.subtitles_dict()
            node = dict(
                kind=content_kinds.VIDEO,
                source_id=self.source_id,
                title=self.name if self.name is not None else self.filename,
                description=self.description,
                author=None,
                files=files,
                language=self.lang,
                license=LICENSE
            )
            return node


def download(source_id):
    tries = 0
    while tries < 4:
        try:
            document = downloader.read(source_id, loadjs=False, session=sess)
        except requests.exceptions.HTTPError as e:
            LOGGER.info("Error: {}".format(e))
        except requests.exceptions.ConnectionError:
            ### this is a weird error, may be it's raised when the webpage
            ### is slow to respond requested resources
            LOGGER.info("Connection error, the resource will be scraped in 5s...")
            time.sleep(3)
        except requests.exceptions.TooManyRedirects as e:
            LOGGER.info("Error: {}".format(e))
        else:
            return document
        tries += 1
    return False


def get_index_range(only_pages):
    if only_pages is None:
            from_i = 0
            to_i = None
    else:
        index = only_pages.split(":")
        if len(index) == 2:
            if index[0] == "":
                from_i = 0
                to_i = int(index[1])
            elif index[1] == "":
                from_i = int(index[0])
                to_i = None
            else:
                index = map(int, index)
                from_i, to_i = index
        elif len(index) == 1:
            from_i = int(index[0])
            to_i = from_i + 1
    return from_i, to_i


# The chef subclass
################################################################################
class PhysLibreTextsChef(JsonTreeChef):
    HOSTNAME = BASE_URL
    TREES_DATA_DIR = os.path.join(DATA_DIR, 'trees')
    SCRAPING_STAGE_OUTPUT_TPL = 'ricecooker_json_tree.json'
    THUMBNAIL = ""

    def __init__(self):
        build_path([PhysLibreTextsChef.TREES_DATA_DIR])
        self.scrape_stage = os.path.join(PhysLibreTextsChef.TREES_DATA_DIR, 
                                PhysLibreTextsChef.SCRAPING_STAGE_OUTPUT_TPL)
        super(PhysLibreTextsChef, self).__init__()

    def pre_run(self, args, options):
        self.download_css_js()
        self.write_tree_to_json(self.scrape(args, options))

    def download_css_js(self):
        r = requests.get("https://raw.githubusercontent.com/learningequality/html-app-starter/master/css/styles.css")
        with open("chefdata/styles.css", "wb") as f:
            f.write(r.content)

        r = requests.get("https://raw.githubusercontent.com/learningequality/html-app-starter/master/js/scripts.js")
        with open("chefdata/scripts.js", "wb") as f:
            f.write(r.content)

    def scrape(self, args, options):
        only_pages = options.get('--only-pages', None)
        only_videos = options.get('--only-videos', None)
        download_video = options.get('--download-video', "1")

        if int(download_video) == 0:
            global DOWNLOAD_VIDEOS
            DOWNLOAD_VIDEOS = False

        global channel_tree
        channel_tree = dict(
                source_domain=PhysLibreTextsChef.HOSTNAME,
                source_id=BASE_URL,
                title=CHANNEL_NAME,
                description="""Offers a “living library,” curated by students, faculty, and outside experts, of open-source textbooks and curricular materials to support popular secondary and college-level academic subjects, primarily in mathematics and sciences."""
[:400], #400 UPPER LIMIT characters allowed 
                thumbnail=None,
                author=AUTHOR,
                language=CHANNEL_LANGUAGE,
                children=[],
                license=LICENSE,
            )

        p_from_i, p_to_i = get_index_range(only_pages)
        v_from_i, v_to_i = get_index_range(only_videos)
        browser = Browser(BASE_URL)
        links = browser.run(p_from_i, p_to_i)
        collections = LinkCollection(links)
        for collection_node in collections.to_node():
            if collection_node is not None:
                channel_tree["children"].append(collection_node)
        return channel_tree

    def write_tree_to_json(self, channel_tree):
        write_tree_to_json_tree(self.scrape_stage, channel_tree)


# CLI
################################################################################
if __name__ == '__main__':
    chef = PhysLibreTextsChef()
    chef.main()
