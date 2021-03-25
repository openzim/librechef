#!/usr/bin/env python

import os
import re
import sys
import json
import time
import logging
import tempfile
from urllib.error import URLError
from urllib.parse import urljoin, urlparse
from collections import OrderedDict

import xxhash
import youtube_dl
import requests
from bs4 import BeautifulSoup
from le_utils.constants import licenses, content_kinds, file_formats
from ricecooker.classes.licenses import get_license
from ricecooker.chefs import JsonTreeChef
from ricecooker.utils import downloader, html_writer
from ricecooker.utils.caching import (
    CacheForeverHeuristic,
    FileCache,
    CacheControlAdapter,
)
from ricecooker.utils.html import download_file
from ricecooker.utils.jsontrees import write_tree_to_json_tree, SUBTITLES_FILE
from ricecooker.utils.zip import create_predictable_zip

from utils import get_name_from_url, build_path
from utils import file_exists, remove_links
from utils import remove_iframes
from utils import link_to_text, remove_scripts

sys.setrecursionlimit(1200)


requests.packages.urllib3.disable_warnings()
requests.packages.urllib3.util.ssl_.DEFAULT_CIPHERS += ":HIGH:!DH:!aNULL"
try:
    requests.packages.urllib3.contrib.pyopenssl.util.ssl_.DEFAULT_CIPHERS += (
        ":HIGH:!DH:!aNULL"
    )
except AttributeError:
    # no pyopenssl support used / needed / available
    pass


DATA_DIR = "chefdata"
DATA_DIR_SUBJECT = ""
COPYRIGHT_HOLDER = "CSU and Merlot"
LICENSE = get_license(licenses.CC_BY_NC_SA, copyright_holder=COPYRIGHT_HOLDER).as_dict()
AUTHOR = "CSU and Merlot"

LOGGER = logging.getLogger()
__logging_handler = logging.StreamHandler()
LOGGER.addHandler(__logging_handler)
LOGGER.setLevel(logging.INFO)

DOWNLOAD_VIDEOS = True
DOWNLOAD_FILES = True
OVERWRITE = True

sess = requests.Session()
cache = FileCache(".webcache")
basic_adapter = CacheControlAdapter(cache=cache)
forever_adapter = CacheControlAdapter(heuristic=CacheForeverHeuristic(), cache=cache)


"""
This is the jerarchery in libretext.

- Collection (CourseLibreText, TextBook, Homework)
  - CategoryA
     * CategoryB (optional)
       * Chapter (optional)
       - Index
         - Chapter

- Collection (Reference, Demos)
     - Index
       - Chapter

- Collection (VisualizationA)
  - CategoryA
     - CategoryB
        - Visualization

- Collection (Ancillary Materials)
  - CategoryA
     * Category B
     - Index
       - Visualization
"""


SUBJECTS = {
    "phys": "https://phys.libretexts.org/",
    "chem": "https://chem.libretexts.org/",
    "bio": "https://bio.libretexts.org/",
    "eng": "https://eng.libretexts.org/",
    "math": "https://math.libretexts.org/",
}

CHANNEL_NAMES = {
    "phys": "LibreTexts Physics",
    "chem": "LibreTexts Chemistry",
    "bio": "LibreTexts Biology",
    "eng": "LibreTexts Engineering",
    "math": "LibreTexts Mathematics",
}


SUBJECTS_THUMBS = {
    "phys": "https://phys.libretexts.org/@api/deki/files/3289/libretexts_section_complete_phys350.png",
    "chem": "https://chem.libretexts.org/@api/deki/files/85425/libretexts_section_complete_chem_sm_124.png",
    "bio": "https://bio.libretexts.org/@api/deki/files/8208/libretexts_section_complete_bio_header.png",
    "eng": "https://eng.libretexts.org/@api/deki/files/1442/libretexts_section_complete_engineering_325.png",
    "math": "https://math.libretexts.org/@api/deki/files/1742/libretexts_section_complete_math350_sigma.png",
}


def hashed(string_to_hash):
    return xxhash.xxh64(string_to_hash.encode("utf-8")).hexdigest()


class Browser:
    def __init__(self, url):
        self.url = url

    def run(self, from_i=1, to_i=None):
        document = download(self.url)
        if document is not None:
            soup = BeautifulSoup(document, "html5lib")  # html.parser
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
        nb_link = 0
        for link in self.links:
            if nb_link > 2:
                break
            nb_link += 1
            self.collection.append(Collection(link.text, link.attrs.get("href", "")))

    def to_node(self):
        nb_col = 0
        for collection in self.collection:
            if nb_col > 2:
                break
            nb_col += 1
            yield collection.to_node()


class Collection:
    url_names = [
        "Courses",
        "Bookshelves",
        "Homework_Exercises",
        "Ancillary_Materials",
        "Visualizations_and_Simulations",
    ]

    def __init__(self, title, link):
        self.title = title
        self.source_id = link
        self.collection = {
            CourseLibreTexts.title: CourseLibreTexts,
            TextBooksTextMaps.title: TextBooksTextMaps,
            HomeworkExercices.title: HomeworkExercices,
            Homework.title: Homework,
            VisualizationPhEt.title: VisualizationPhEt,
            VisualizationsSimulations.title: VisualizationsSimulations,
        }
        self.nb_topic = 2

    def to_node(self):
        try:
            Topic = self.collection[self.title]
        except KeyError:
            LOGGER.error("Collection Not Found: {}".format(self.title))
        else:
            LOGGER.info(self.title)
            topic = Topic(self.source_id)
            topic.populate_thumbnails()
            topic.units()
            return topic.to_node()


class Topic(object):
    def __init__(self, url, title=None):
        if title is not None:
            self.title = title
        self.source_id = url
        self.urls = Browser(self.source_id).run()
        self.lang = "en"
        self.tree_nodes = OrderedDict()
        self.thumbnails_links = {}
        self.description = ""
        self.soup = self.to_soup()
        LOGGER.info("- " + self.title)

    def to_soup(self):
        document = download(self.source_id)
        if document is not None:
            return BeautifulSoup(document, "html5lib")  # html5lib

    def __iter__(self):
        return self.urls

    def __next__(self):
        return next(self.urls)

    def populate_thumbnails(self):
        pass

    def add_node(self, node):
        if node is not None:
            self.tree_nodes[node["source_id"]] = node

    def to_node(self):
        return dict(
            kind=content_kinds.TOPIC,
            source_id=self.title,
            title=self.title,
            description=self.description,
            language=self.lang,
            author="",
            license=LICENSE,
            children=list(self.tree_nodes.values()),
        )


class CourseLibreTexts(Topic):
    title = "Course Shells"  # previously "Campus Courses", "Course LibreTexts"

    def units(self):
        nb_url = 0
        for url in self:
            if nb_url > 2:
                break
            nb_url += 1
            topic = Topic(url.attrs.get("href"), title=url.text)
            for link in topic:
                print("CourseLibreTexts", link)
                course_index = CourseIndex(link.text, link.attrs.get("href"))
                course_index.description = link.attrs.get("title")
                path = [
                    DATA_DIR,
                    DATA_DIR_SUBJECT,
                    hashed(topic.title),
                    hashed(link.text),
                ]
                course_index.index(build_path(path))
                topic.add_node(course_index.to_node())
            self.add_node(topic.to_node())


class TextBooksTextMaps(Topic):
    title = "Bookshelves"  # "TextBooks & TextMaps"

    def populate_thumbnails(self):
        self.thumbnails_links = thumbnails_links(self.soup, "li", "mt-sortable-listing")

    def units(self):
        base_path = [DATA_DIR, DATA_DIR_SUBJECT, hashed(self.title)]
        nb_chapter = 0
        for chapter_link in self:
            if nb_chapter > 2:
                break
            nb_chapter += 1
            course_index = CourseIndex(
                chapter_link.text, chapter_link.attrs.get("href", "")
            )
            course_index.description = chapter_link.attrs.get("title")
            course_index.thumbnail = self.thumbnails_links.get(
                chapter_link.attrs.get("href", ""), None
            )
            course_index.index(build_path(base_path + [hashed(chapter_link.text)]))
            self.add_node(course_index.to_node())


class HomeworkExercices(Topic):
    title = "Homework Exercises"

    def populate_thumbnails(self):
        self.thumbnails_links = thumbnails_links(self.soup, "li", "mt-sortable-listing")

    def units(self):
        base_path = [DATA_DIR, DATA_DIR_SUBJECT, hashed(self.title)]
        nb_chapter = 0
        for chapter_link in self:
            if nb_chapter > 2:
                break
            nb_chapter += 1
            course_index = CourseIndex(
                chapter_link.text, chapter_link.attrs.get("href", "")
            )
            course_index.description = chapter_link.attrs.get("title")
            course_index.thumbnail = self.thumbnails_links.get(
                chapter_link.attrs.get("href", ""), None
            )
            course_index.index(build_path(base_path + [hashed(chapter_link.text)]))
            self.add_node(course_index.to_node())


class Homework(HomeworkExercices):  # Alias for homework and exercices
    title = "Homework"


class VisualizationPhEt(Topic):
    title = "Ancillary Materials"

    def units(self):
        base_path = [DATA_DIR, DATA_DIR_SUBJECT, hashed(self.title)]
        nb_chapter = 0
        for chapter_link in self:
            if nb_chapter > 2:
                break
            nb_chapter += 1
            if chapter_link.text.strip() in [
                "CalcPlot3D Interactive Figures",
                "GeoGebra Simulations",
            ]:
                continue
            course_index = CourseIndex(
                chapter_link.text, chapter_link.attrs.get("href", "")
            )
            course_index.description = chapter_link.attrs.get("title")
            course_index.thumbnail = self.thumbnails_links.get(
                chapter_link.attrs.get("href", ""), None
            )
            course_index.index(build_path(base_path + [hashed(chapter_link.text)]))
            self.add_node(course_index.to_node())


class VisualizationsSimulations(VisualizationPhEt):
    title = "Visualizations and Simulations"


def thumbnails_links(soup, tag, class_):
    if soup is not None:
        courses_list = soup.find_all(tag, class_=class_)
        thumnails = {}
        for course_li in courses_list:
            link = course_li.find("a").get("href")
            img = course_li.find("img")
            if img is not None:
                thumnails[link] = img["src"]
        return thumnails


def save_thumbnail(url, title):
    import imghdr
    from io import BytesIO

    try:
        r = requests.get(url)
    except:
        return None
    else:
        img_buffer = BytesIO(r.content)
        img_ext = imghdr.what(img_buffer)
        if img_ext in ["jpeg", "png"]:
            filename = "{}.{}".format(title, img_ext)
            base_dir = build_path([DATA_DIR, DATA_DIR_SUBJECT, "thumbnails"])
            filepath = os.path.join(base_dir, filename)
            with open(filepath, "wb") as f:
                f.write(img_buffer.read())
            return filepath


class CourseIndex(object):
    def __init__(self, title, url, visited_urls=None):
        self.source_id = url
        self.title = title
        self.lang = "en"
        self.description = None
        self.tree_nodes = OrderedDict()
        self.soup = self.to_soup()
        self.author()
        self._thumbnail = None
        self.visited_urls = visited_urls if visited_urls is not None else set([])
        LOGGER.info("----- Course Index title: " + self.title)
        LOGGER.info("-----    url: " + self.source_id)

    def to_soup(self, loadjs=False):
        document = download(self.source_id, loadjs=loadjs)
        try:
            response = requests.get(self.source_id, timeout=20)
        except Exception as exc:
            LOGGER.error(exc)
        else:
            if response.status_code == 200:
                self.source_id = response.url
            if document is not None:
                return BeautifulSoup(document, "html5lib")  # html5lib

    @property
    def thumbnail(self):
        return self._thumbnail

    @thumbnail.setter
    def thumbnail(self, url):
        self._thumbnail = save_thumbnail(url, self.title)

    def author(self):
        if self.soup is not None:
            div = self.soup.find("div", "mt-author-container")
            if div is not None:
                tag_a = div.find(
                    lambda tag: tag.name == "a"
                    and tag.findParent("li", class_="mt-author-information")
                )
                if tag_a is not None:
                    return tag_a.text

    def index(self, base_path):
        base_url_path_elems = urlparse(self.source_id).path.split("/")
        base_url_classes = Collection.url_names
        if (
            len(base_url_path_elems) == 2
            and base_url_path_elems[1] in base_url_classes
            or len(base_url_path_elems) == 1
        ):
            return "cycle"
        if self.soup is None:
            retry_times = 0
            while retry_times < 5 and self.soup is None:
                self.soup = self.to_soup()
                LOGGER.info("Retrying")
                retry_times += 1
            if self.soup is None:
                LOGGER.error("Could not download content ")
                return
        courses_link = self.soup.find_all(
            lambda tag: tag.name == "a"
            and tag.findParent("dt", class_="mt-listing-detailed-title")
        )
        if len(courses_link) == 0:
            courses_link = self.soup.find_all(
                lambda tag: tag.name == "a"
                and tag.findParent("li", class_="mt-sortable-listing")
            )
        if len(courses_link) == 0:
            query = QueryPage(self.soup, self.source_id)
            body = query.body()
            if body is not None:
                courses_link = body.find_all("a")
            else:
                courses_link = self.soup.find_all(
                    lambda tag: tag.name == "a"
                    and tag.findParent("div", class_="wiki-tree")
                )
                if len(courses_link) == 0:
                    return
                else:
                    LOGGER.info("OK")

        thumbnails = thumbnails_links(self.soup, "li", "mt-sortable-listing")

        index_base_path = base_path  # build_path([base_path])
        nb_items = 0
        for course_link in courses_link:
            course_link_href = course_link.attrs.get("href", "")
            if course_link_href in self.visited_urls:
                continue
            if nb_items > 2:
                break
            print("MAIN COURSE LINK", nb_items, course_link_href)
            nb_items += 1
            self.visited_urls.add(course_link_href)
            document = download(course_link_href)
            chapter_basepath = build_path([index_base_path, hashed(course_link.text)])
            if document is not None:
                query = QueryPage(
                    BeautifulSoup(document, "html.parser"), course_link_href
                )

                course_body = query.body()
                nb_chapter = 0
                if course_body is not None:
                    course = Course(course_link.text, course_link_href, self.author())
                    course.thumbnail = thumbnails.get(course_link_href, None)
                    for chapter_title in course_body.find_all("a"):
                        chapter_href = chapter_title.attrs.get("href", "")
                        if nb_chapter > 2:
                            break
                        print("CHAPTER", nb_chapter, chapter_href)
                        nb_chapter += 1
                        chapter = Chapter(chapter_title.text, chapter_href)
                        chapter.to_file(chapter_basepath)
                        node = chapter.to_node()
                        course.add_node(node)
                    self.add_node(course.to_node())
                else:
                    if course_link.text.strip() == "Agenda":
                        agenda = AgendaOrFlatPage(course_link.text, course_link_href)
                        agenda.to_file(chapter_basepath)
                        self.add_node(agenda.to_node())
                    elif course_link.text.strip() in [
                        "CalcPlot3D Interactive Figures",
                        "GeoGebra Simulations",
                    ]:  # Not supported
                        pass
                    else:
                        course_index = CourseIndex(
                            course_link.text,
                            course_link_href,
                            visited_urls=self.visited_urls,
                        )
                        result = course_index.index(
                            build_path([base_path, hashed(course_link.text)])
                        )
                        if result is None:
                            course_index_node = course_index.to_node()
                            if len(course_index_node["children"]) == 0:
                                chapter = Chapter(course_link.text, course_link_href)
                                chapter.to_file(chapter_basepath)
                                node = chapter.to_node()
                                self.add_node(node)
                            else:
                                self.add_node(course_index_node)
            # break

    def add_node(self, node):
        if node is not None:
            self.tree_nodes[node["source_id"]] = node

    def to_node(self):
        return dict(
            kind=content_kinds.TOPIC,
            source_id=self.source_id,
            title=self.title,
            description=self.description,
            language=self.lang,
            thumbnail=self.thumbnail,
            author=self.author(),
            license=LICENSE,
            children=list(self.tree_nodes.values()),
        )


class Course(object):
    def __init__(self, title, url, author):
        self.source_id = url
        self.title = title
        self.author = author
        self.lang = "en"
        self._thumbnail = None
        self.tree_nodes = OrderedDict()
        LOGGER.info("------- Course: " + self.title)
        LOGGER.info("-------   url: " + self.title)

    @property
    def thumbnail(self):
        return self._thumbnail

    @thumbnail.setter
    def thumbnail(self, url):
        self._thumbnail = save_thumbnail(url, self.title)

    def add_node(self, node):
        self.tree_nodes[node["source_id"]] = node

    def to_node(self):
        return dict(
            kind=content_kinds.TOPIC,
            source_id=self.source_id,
            title=self.title,
            description="",
            language=self.lang,
            thumbnail=self.thumbnail,
            author=self.author,
            license=LICENSE,
            children=list(self.tree_nodes.values()),
        )


class AgendaOrFlatPage(object):
    def __init__(self, title, url):
        self.source_id = url
        self.title = title.replace("/", "_")
        self.soup = self.to_soup()
        self.lang = "en"
        self.filepath = None
        LOGGER.info("--- Agenda (Flat Page)" + self.title)
        LOGGER.info("---   url" + self.source_id)

    def write_css_js(self, filepath):
        with html_writer.HTMLWriter(filepath, "a") as zipper, open(
            "chefdata/styles.css"
        ) as f:
            content = f.read()
            zipper.write_contents("styles.css", content, directory="css/")

        with html_writer.HTMLWriter(filepath, "a") as zipper, open(
            "chefdata/scripts.js"
        ) as f:
            content = f.read()
            zipper.write_contents("scripts.js", content, directory="js/")

    def body(self):
        if self.soup is not None:
            return self.soup.find("section", class_="mt-content-container")

    def clean(self, content):
        link_to_text(content)
        remove_links(content)
        remove_iframes(content)
        remove_scripts(content)
        return content

    def to_soup(self):
        document = download(self.source_id)
        if document is not None:
            return BeautifulSoup(document, "html.parser")

    def write_index(self, filepath, content):
        with html_writer.HTMLWriter(filepath, "w") as zipper:
            zipper.write_index_contents(content)

    def to_file(self, base_path):
        filepath = "{path}/{name}.zip".format(path=base_path, name=hashed(self.title))
        if file_exists(filepath) and OVERWRITE is False:
            self.filepath = filepath
            LOGGER.info("Not overwrited file {}".format(self.filepath))
        elif self.body() is not None:
            self.filepath = filepath
            body = self.clean(self.body())
            try:
                string_to_write = '<html><head><meta charset="utf-8"><link rel="stylesheet" href="css/styles.css"></head><body><div class="main-content-with-sidebar">{}</div><script src="js/scripts.js"></body></html>'.format(
                    body
                )
                self.write_index(
                    self.filepath,
                    string_to_write.encode("utf-8", errors="surrogatepass"),
                )
            except RuntimeError as e:
                self.filepath = None
                LOGGER.error(e)
            else:
                self.write_css_js(self.filepath)
        else:
            LOGGER.error("Empty body in {}".format(self.source_id))

    def to_node(self):
        if self.filepath is not None:
            return dict(
                kind=content_kinds.HTML5,
                source_id=self.source_id,
                title=self.title,
                description="",
                thumbnail=None,
                author="",
                files=[dict(file_type=content_kinds.HTML5, path=self.filepath)],
                language=self.lang,
                license=LICENSE,
            )


class Chapter(AgendaOrFlatPage):
    def __init__(self, title, url):
        self.title = title.replace("/", "_")
        self.source_id = url
        self.soup = self.to_soup()
        self.lang = "en"
        self.filepath = None
        self.video_nodes = None
        self.pdf_nodes = None
        self.phet_nodes = None
        self.author = self.get_author()
        LOGGER.info("--------- Chapter: " + self.title)
        LOGGER.info("---------   url: " + self.source_id)

    def get_author(self):
        if self.soup is not None:
            tag_a = self.soup.find(
                lambda tag: tag.name == "a"
                and tag.findParent("li", "mt-author-information")
            )
            if tag_a is not None:
                return tag_a.text

    def mathjax(self):
        if self.soup is not None:
            scripts = self.soup.find_all("script", type="text/x-mathjax-config")
            return "".join([str(s) for s in scripts])

    def mathjax_dependences(self, filepath):
        mathajax_path = "../MathJax/"
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
            "extensions/TeX/boldsymbol.js",
            "extensions/TeX/cancel.js",
            "jax/output/HTML-CSS/jax.js",
            "jax/output/HTML-CSS/fonts/TeX/fontdata.js",
            "jax/output/HTML-CSS/autoload/mtable.js",
            # "jax/output/HTML-CSS/imageFonts.js"
        ]
        for dep in dependences:
            filename = dep.split("/")[-1]
            dep_path = "/".join(dep.split("/")[:-1])
            dep_file_path = os.path.join(mathajax_path, dep_path, filename)
            with html_writer.HTMLWriter(filepath, "a") as zipper, open(
                dep_file_path
            ) as f:
                content = f.read()
                zipper.write_contents(filename, content, directory="js/" + dep_path)

    def to_local_images(self, content):
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

    def build_video_nodes(self, base_path, content):
        videos_url = self.get_videos_urls(content)
        base_path = build_path([DATA_DIR, DATA_DIR_SUBJECT, "videos"])
        video_nodes = []
        for video_url in videos_url:
            if YouTubeResource.is_youtube(video_url) and not YouTubeResource.is_channel(
                video_url
            ):
                video = YouTubeResource(video_url, lang=self.lang)
                video.download(download=DOWNLOAD_VIDEOS, base_path=base_path)
                node = video.to_node()
                if node is not None:
                    video_nodes.append(node)
        return video_nodes

    def build_phet_nodes(self, base_path, content):
        phet_urls = self.get_phet_simulations(content)
        base_path = build_path([DATA_DIR, DATA_DIR_SUBJECT, "phet"])
        phet_nodes = []
        for phet_url in phet_urls:
            phet = PhetResource(self.title, phet_url, lang=self.lang)
            phet.description = None
            phet.download(download=True, base_path=base_path)
            node = phet.to_node()
            if node is not None:
                phet_nodes.append(node)
        return phet_nodes

    def get_videos_urls(self, content):
        urls = set([])
        if content is not None:
            video_urls = content.find_all(
                lambda tag: tag.name == "a"
                and tag.attrs.get("href", "").find("youtube") != -1
                or tag.attrs.get("href", "").find("youtu.be") != -1
                or tag.text.lower() == "youtube"
            )

            for video_url in video_urls:
                urls.add(video_url.get("href", ""))

            for iframe in content.find_all("iframe"):
                url = iframe["src"]
                if YouTubeResource.is_youtube(url) and not YouTubeResource.is_channel(
                    url
                ):
                    urls.add(YouTubeResource.transform_embed(url))
        return urls

    def get_pdfs_urls(self, content):
        urls = set([])
        if content is not None:
            pdf_urls = content.findAll(
                lambda tag: tag.name == "a"
                and tag.attrs.get("href", "").endswith(".pdf")
            )
            for pdf_url in pdf_urls:
                urls.add(pdf_url.get("href", ""))
        return urls

    def get_phet_simulations(self, content):
        urls = set([])
        if content is not None:
            phet_urls = content.find_all(
                lambda tag: tag.name == "iframe"
                and tag.attrs.get("src", "").find("phet.colorado.edu") != -1
            )
            for phet_url in phet_urls:
                urls.add(phet_url.get("src", ""))
        return urls

    def write_images(self, filepath, images):
        with html_writer.HTMLWriter(filepath, "a") as zipper:
            for img_src, img_filename in images.items():
                try:
                    if img_src.startswith("data:image/") or img_src.startswith(
                        "file://"
                    ):
                        pass
                    else:
                        # zipper.write_url(img_src, img_filename, directory="")
                        zipper.write_contents(
                            img_filename,
                            downloader.read(img_src, timeout=5, session=sess),
                            directory="",
                        )
                except (
                    requests.exceptions.HTTPError,
                    requests.exceptions.ConnectTimeout,
                    requests.exceptions.ConnectionError,
                    FileNotFoundError,
                    requests.exceptions.ReadTimeout,
                ):
                    pass

    def build_pdfs_nodes(self, base_path, content):
        pdfs_urls = self.get_pdfs_urls(content)
        base_path = build_path([base_path, "pdfs"])
        pdf_nodes = []
        for pdf_url in pdfs_urls:
            pdf_file = File(pdf_url, lang=self.lang, name=self.title)
            pdf_file.download(download=DOWNLOAD_FILES, base_path=base_path)
            node = pdf_file.to_node()
            if node is not None:
                pdf_nodes.append(node)
        return pdf_nodes

    def write_mathjax(self, filepath):
        script_tag = self.soup.find(
            lambda tag: tag.name == "script"
            and tag.attrs.get("src", "").find("MathJax.js") != -1
        )
        filepath_js = "chefdata/MathJax.js"
        if not file_exists(filepath_js) and script_tag:
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
        filepath = "{path}/{name}.zip".format(path=base_path, name=hashed(self.title))
        if self.body() is not None:
            self.video_nodes = self.build_video_nodes(base_path, self.body())
            self.pdf_nodes = self.build_pdfs_nodes(base_path, self.body())
            self.phet_nodes = self.build_phet_nodes(base_path, self.body())
        else:
            LOGGER.error("Empty body in {}".format(self.source_id))
            return

        if file_exists(filepath) and OVERWRITE is False:
            self.filepath = filepath
            LOGGER.info("Not overwrited file {}".format(self.filepath))
        else:
            self.filepath = filepath
            mathjax_scripts = self.mathjax()
            body = self.clean(self.body())
            images = self.to_local_images(body)
            try:
                string_to_write = '<html><head><meta charset="utf-8"><link rel="stylesheet" href="css/styles.css"></head><body><div class="main-content-with-sidebar">{}</div><script src="js/scripts.js"></script>{}<script src="js/MathJax.js?config=TeX-AMS_HTML"></script></body></html>'.format(
                    body, mathjax_scripts
                )
                self.write_index(
                    self.filepath,
                    string_to_write.encode("utf-8", errors="surrogatepass"),
                )
            except RuntimeError as e:
                self.filepath = None
                LOGGER.error(e)
            else:
                self.write_images(self.filepath, images)
                self.write_css_js(self.filepath)
                self.write_mathjax(self.filepath)
                self.mathjax_dependences(self.filepath)

    def topic_node(self):
        return dict(
            kind=content_kinds.TOPIC,
            source_id=self.source_id,
            title=self.title,
            description="",
            language=self.lang,
            author="",
            license=LICENSE,
            thumbnail=None,
            children=[],
        )

    def html_node(self):
        if self.filepath is not None:
            return dict(
                kind=content_kinds.HTML5,
                source_id=self.source_id,
                title=self.title,
                description="",
                thumbnail=None,
                author=self.author,
                files=[dict(file_type=content_kinds.HTML5, path=self.filepath)],
                language=self.lang,
                license=LICENSE,
            )

    def add_to_node(self, node, nodes):
        for node_ in nodes:
            if node_ is not None:
                node["children"].append(node_)

    def to_node(self):
        if self.phet_nodes is not None and len(self.phet_nodes) > 0:
            if len(self.phet_nodes) > 1:
                node = self.topic_node()
                self.add_to_node(node, self.phet_nodes)
            else:
                node = self.phet_nodes[0]
        elif (
            self.video_nodes is not None
            and len(self.video_nodes) > 0
            or self.pdf_nodes is not None
            and len(self.pdf_nodes) > 0
        ):
            node = self.topic_node()
            node["children"].append(self.html_node())
            self.add_to_node(node, self.video_nodes)
            self.add_to_node(node, self.pdf_nodes)
        else:
            node = self.html_node()
        return node


class QueryPage:
    def __init__(self, soup, source_id):
        self.soup = soup
        self.get_id()
        self.source_id = source_id

    def get_id(self):
        page_global_settings = self.soup.find("script", id="mt-global-settings")
        if page_global_settings:
            self.x_deki_token = json.loads(page_global_settings.text).get(
                "apiToken", None
            )
        else:
            self.x_deki_token = None

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
            url = "{}@api/deki/pages/=Template%253AMindTouch%252FIDF3%252FViews%252FTopic_hierarchy/contents?dream.out.format=json&origin=mt-web&pageid={}&draft=false&guid={}".format(
                BASE_URL, self.page_id, self.guid
            )
            try:
                r = requests.get(
                    url,
                    headers={
                        "x-deki-token": "{}".format(self.x_deki_token),
                        "x-deki-client": "mindtouch-martian",
                        "x-deki-requested-with": "XMLHttpRequest",
                    },
                )
                json_obj = r.json()
                body = json_obj.get("body", None)
                if body is not None:
                    return BeautifulSoup(body, "html.parser")
            except Exception as e:
                LOGGER.error(e)
                return None


class YouTubeResource(object):
    def __init__(
        self,
        source_id,
        name=None,
        type_name="Youtube",
        lang="en",
        embeded=False,
        section_title=None,
        description=None,
    ):
        LOGGER.info("     + Resource Type: {}".format(type_name))
        LOGGER.info("     - URL: {}".format(source_id))
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

    @staticmethod
    def is_channel(url):
        return "channel" in url

    def get_video_info(self, download_to=None, subtitles=True):
        ydl_options = {
            "writesubtitles": subtitles,
            "allsubtitles": subtitles,
            "no_warnings": True,
            "restrictfilenames": True,
            "continuedl": True,
            "quiet": False,
            "format": "bestvideo[height<={maxheight}][ext=mp4]+bestaudio[ext=m4a]/best[height<={maxheight}][ext=mp4]".format(
                maxheight="480"
            ),
            "outtmpl": "{}/%(id)s".format(download_to),
            "noplaylist": True,
        }

        with youtube_dl.YoutubeDL(ydl_options) as ydl:
            try:
                ydl.add_default_info_extractors()
                info = ydl.extract_info(
                    self.source_id, download=(download_to is not None)
                )
                return info
            except (
                youtube_dl.utils.DownloadError,
                youtube_dl.utils.ContentTooShortError,
                youtube_dl.utils.ExtractorError,
            ) as e:
                LOGGER.info("An error occured " + str(e))
                LOGGER.info(self.source_id)
            except KeyError as e:
                LOGGER.info(str(e))

    def subtitles_dict(self):
        subs = []
        video_info = self.get_video_info()
        if video_info is not None:
            video_id = video_info.get("id", None)
            if "subtitles" in video_info and video_id is not None:
                subtitles_info = video_info["subtitles"]
                LOGGER.info("Subtitles: {}".format(",".join(subtitles_info.keys())))
                for language in subtitles_info.keys():
                    subs.append(
                        dict(
                            file_type=SUBTITLES_FILE,
                            youtube_id=video_id,
                            language=language,
                        )
                    )
        return subs

    def download(self, download=True, base_path=None):
        download_to = build_path([base_path])
        for i in range(2):
            try:
                info = self.get_video_info(download_to=download_to, subtitles=False)
                if info is not None:
                    LOGGER.info(
                        "    + Video resolution: {}x{}".format(
                            info.get("width", ""), info.get("height", "")
                        )
                    )
                    if self.description is None:
                        self.description = info.get("description", None)
                    self.filepath = os.path.join(
                        download_to, "{}.mp4".format(info["id"])
                    )
                    self.filename = info["title"]
                    if (
                        self.filepath is not None
                        and os.stat(self.filepath).st_size == 0
                    ):
                        LOGGER.info("    + Empty file")
                        self.filepath = None
            except (ValueError, IOError, OSError, URLError, ConnectionResetError) as e:
                LOGGER.info(e)
                LOGGER.info("Download retry")
                time.sleep(0.8)
            except (
                youtube_dl.utils.DownloadError,
                youtube_dl.utils.ContentTooShortError,
                youtube_dl.utils.ExtractorError,
                OSError,
            ) as e:
                LOGGER.info(
                    "    + An error ocurred, may be the video is not available."
                )
                return
            except (OSError, KeyError) as e:
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
                license=LICENSE,
            )
            return node


class PhetResource(object):
    def __init__(self, title, url, lang="en"):
        self.source_id = url
        self.title = title
        self.lang = "en"
        self.filepath = None
        self.description = None

    def download(self, download=True, base_path=None):
        # download_to = build_path([base_path])
        dst = tempfile.mkdtemp()
        download_file(
            self.source_id,
            dst,
            filename="index.html",
            request_fn=sess.get,
            middleware_callbacks=[self.process_sim_html],
        )
        self.filepath = create_predictable_zip(dst)

    ##https://github.com/learningequality/sushi-chef-phet/blob/master/chef.py
    def process_sim_html(self, content, destpath, **kwargs):
        """Remove various pieces of the code that make requests to online resources, to avoid using
        bandwidth for users expecting a fully offline or zero-rated website."""

        # remove "are we online" check
        content = content.replace(
            "check:function(){var t=this", "check:function(){return;var t=this"
        )

        # remove online links from "about" modal
        content = content.replace(
            "getLinks:function(", "getLinks:function(){return [];},doNothing:function("
        )

        soup = BeautifulSoup(content, "html.parser")

        for script in soup.find_all("script"):
            # remove Google Analytics and online image bug requests
            if "analytics.js" in str(script):
                script.extract()
            # remove menu options that link to online resources
            if 'createTandem("phetWebsiteButton' in str(script):
                script.string = re.compile(
                    '\{[^}]+createTandem\("phetWebsiteButton"\).*createTandem\("getUpdate"[^\}]*\},'
                ).sub("", script.string.replace("\n", " "))

        return str(soup)

    def to_node(self):
        if self.filepath is not None:
            return dict(
                kind=content_kinds.HTML5,
                source_id=self.source_id,
                title=self.title,
                description=self.description,
                thumbnail=None,
                author="",
                files=[dict(file_type=content_kinds.HTML5, path=self.filepath)],
                language=self.lang,
                license=get_license(
                    licenses.CC_BY,
                    copyright_holder="PhET Interactive Simulations, University of Colorado Boulder",
                ).as_dict(),
            )


class File(object):
    def __init__(self, source_id, lang="en", name=None):
        self.filename = get_name_from_url(source_id)
        self.source_id = (
            urljoin(BASE_URL, source_id) if source_id.startswith("/") else source_id
        )
        self.filepath = None
        self.lang = lang
        self.name = "{}_{}".format(name, self.filename)

    def download(self, download=True, base_path=None):
        try:
            if download is False:
                return
            response = sess.get(self.source_id)
            content_type = response.headers.get("content-type")
            if content_type is not None and "application/pdf" in content_type:
                self.filepath = os.path.join(base_path, self.filename)
                with open(self.filepath, "wb") as f:
                    for chunk in response.iter_content(10000):
                        f.write(chunk)
                LOGGER.info(
                    "    - Get file: {}, node name: {}".format(self.filename, self.name)
                )
        except requests.exceptions.HTTPError as e:
            LOGGER.info("Error: {}".format(e))
        except requests.exceptions.ConnectionError:
            ### this is a weird error, may be it's raised when the webpage
            ### is slow to respond requested resources
            LOGGER.info("Connection error, the resource will be scraped in 5s...")
            time.sleep(3)
        except requests.exceptions.ReadTimeout as e:
            LOGGER.error("Error: {}".format(e))
        except requests.exceptions.TooManyRedirects as e:
            LOGGER.error("Error: {}".format(e))
        except requests.exceptions.InvalidSchema as e:
            LOGGER.error("Error: {}".format(e))

    def to_node(self):
        if self.filepath is not None:
            node = dict(
                kind=content_kinds.DOCUMENT,
                source_id=self.source_id,
                title=self.name,
                description="",
                files=[dict(file_type=content_kinds.DOCUMENT, path=self.filepath)],
                language=self.lang,
                license=LICENSE,
            )
            return node


def download(source_id, loadjs=False):
    tries = 0
    while tries < 20:
        try:
            document = downloader.read(source_id, loadjs=loadjs, session=sess)
        except requests.exceptions.HTTPError as e:
            LOGGER.info("Error: {}".format(e))
        except requests.exceptions.ConnectionError:
            ### this is a weird error, may be it's raised when the webpage
            ### is slow to respond requested resources
            LOGGER.info("Connection error, the resource will be scraped in 5s...")
            time.sleep(5 * tries)
        except requests.exceptions.TooManyRedirects as e:
            LOGGER.info("Error: {}".format(e))
        except (requests.exceptions.InvalidURL, FileNotFoundError) as e:
            LOGGER.error(e)
        else:
            if document is not None:
                return document
        tries += 1
    # return False


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
class LibreTextsChef(JsonTreeChef):
    TREES_DATA_DIR = os.path.join(DATA_DIR, "trees")
    SCRAPING_STAGE_OUTPUT_TPL = "ricecooker_{subject}_json_tree.json"
    THUMBNAIL = ""

    def pre_run(self, args, options):
        build_path([LibreTextsChef.TREES_DATA_DIR])
        self.download_css_js()
        channel_tree = self.scrape(args, options)
        self.write_tree_to_json(channel_tree)
        # subject = options.get('--subject', "phys")
        # self.RICECOOKER_JSON_TREE = LibreTextsChef.SCRAPING_STAGE_OUTPUT_TPL.format(subject=subject)

    def download_css_js(self):
        r = requests.get(
            "https://raw.githubusercontent.com/learningequality/html-app-starter/master/css/styles.css"
        )
        with open("chefdata/styles.css", "wb") as f:
            f.write(r.content)

        r = requests.get(
            "https://raw.githubusercontent.com/learningequality/html-app-starter/master/js/scripts.js"
        )
        with open("chefdata/scripts.js", "wb") as f:
            f.write(r.content)

    def scrape(self, args, options):
        only_pages = options.get("--only-pages", None)
        only_videos = options.get("--only-videos", None)
        download_video = options.get("--download-video", "1")
        subject = options.get("--subject", "phys")
        overwrite = options.get("--overwrite", "1")
        run_test = bool(int(options.get("--test", "0")))
        new_channel_id = options.get(
            "--channel-id", None
        )  # can use {subject} as a placeholder
        channel_name = options.get(
            "--channel-name", None
        )  # can use this to set a custom channel name
        channel_description = options.get(
            "--channel-description", None
        )  # can use this to set a custom channel description
        channel_language = options.get(
            "--channel-language", None
        )  # can use this to set channel language

        global DATA_DIR_SUBJECT
        global OVERWRITE
        OVERWRITE = bool(int(overwrite))
        DATA_DIR_SUBJECT = subject
        self.RICECOOKER_JSON_TREE = LibreTextsChef.SCRAPING_STAGE_OUTPUT_TPL.format(
            subject=subject
        )
        self.scrape_stage = os.path.join(
            LibreTextsChef.TREES_DATA_DIR, self.RICECOOKER_JSON_TREE
        )

        LOGGER.info("Scraping {}".format(SUBJECTS[subject]))
        if int(download_video) == 0:
            global DOWNLOAD_VIDEOS
            DOWNLOAD_VIDEOS = False

        global channel_tree
        channel_tree = dict(
            source_domain=SUBJECTS[subject],
            source_id=new_channel_id.format(subject=subject),
            title=channel_name or CHANNEL_NAMES.get(subject, "LibreTexts Channel"),
            description="""Offers a “living library,” curated by students, faculty, and outside experts, of open-source textbooks and curricular materials to support popular secondary and college-level academic subjects, primarily in mathematics and sciences."""[
                :400
            ],
            thumbnail=SUBJECTS_THUMBS[subject],
            author=AUTHOR,
            language=channel_language or "en",
            children=[],
            license=LICENSE,
        )

        global BASE_URL
        BASE_URL = SUBJECTS[subject]

        if run_test is True:
            return test(channel_tree)
        else:
            p_from_i, p_to_i = get_index_range(only_pages)
            v_from_i, v_to_i = get_index_range(only_videos)
            browser = Browser(BASE_URL)
            links = browser.run(p_from_i, p_to_i)
            collections = LinkCollection(links)
            nb_col = 0
            for collection_node in collections.to_node():
                if nb_col > 2:
                    break
                nb_col += 1
                if collection_node is not None:
                    channel_tree["children"].append(collection_node)
            return channel_tree

    def write_tree_to_json(self, channel_tree):
        write_tree_to_json_tree(self.scrape_stage, channel_tree)


def test(channel_tree):
    base_path = build_path([DATA_DIR, DATA_DIR_SUBJECT, hashed("test one: a3")])
    c = Chapter(
        "test: one : one",
        # "https://eng.libretexts.org/Bookshelves/Computer_Science/Book%3A_Eloquent_JavaScript_(Haverbeke)/Part_1%3A_Language/05%3A_Higher-order_Functions",
        "https://eng.libretexts.org/Bookshelves/Materials_Science/TLP_Library_I/03%3A_Atomic_Force_Microscopy/3.07%3A_Scanner_Related_Artefacts",
    )
    c.to_file(base_path)
    channel_tree["children"].append(c.to_node())
    return channel_tree


# CLI
################################################################################
if __name__ == "__main__":
    chef = LibreTextsChef()
    chef.main()
