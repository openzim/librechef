from git import Repo
import ntpath
import os
from pathlib import Path


def if_dir_exists(filepath):
    file_ = Path(filepath)
    return file_.is_dir()


def if_file_exists(filepath):
    my_file = Path(filepath)
    return my_file.is_file()


def remove_links(content):
    if content is not None:
        for link in content.find_all("a"):
            link.replaceWithChildren()


def get_name_from_url(url):
    head, tail = ntpath.split(url)
    params_index = tail.find("&")
    if params_index != -1:
        tail = tail[:params_index]
    params_index = tail.find("?")
    if params_index != -1:
        tail = tail[:params_index]

    basename = ntpath.basename(url)
    params_b_index = basename.find("&")
    if params_b_index != -1:
        basename = basename[:params_b_index]
    return tail or basename


def get_name_from_url_no_ext(url):
    path = get_name_from_url(url)
    path_split = path.split(".")
    if len(path_split) > 1:
        name = ".".join(path_split[:-1])
    else:
        name = path_split[0]
    return name


def clone_repo(git_url, repo_dir):
    if not if_dir_exists(repo_dir):
        print("Cloning repository {}".format(git_url))
        Repo.clone_from(git_url, repo_dir)
    else:
        print("Pulling data from repository {}".format(git_url))
        repo = Repo(repo_dir)
        for info in repo.remotes.origin.pull():
            print(info)


def build_path(levels):
    path = os.path.join(*levels)
    if not if_dir_exists(path):
        os.makedirs(path)
    return path


def get_video_resolution_format(video, maxvres=720, ext="mp4"):
    formats = [(int(s.resolution.split("x")[1]), s.extension, s) for s in video.videostreams]
    formats = sorted(formats, key=lambda x: x[0])
    best = None
    for r, x, stream in formats:
        if r <= maxvres and x == ext:
            best = stream
    if best is None:
        return video.getbest(preftype=ext)
    else:
        return best


def get_node_from_channel(source_id, channel_tree, exclude=None):
    parent = channel_tree["children"]
    while len(parent) > 0:
        for children in parent:
            if children is not None and children["source_id"] == source_id:
                return children
        nparent = []
        for children in parent:
            try:
                if children is not None and children["title"] != exclude:
                    nparent.extend(children["children"])
            except KeyError:
                pass
        parent = nparent


def get_level_map(tree, levels):
    actual_node = levels[0]
    r_levels = levels[1:]
    for children in tree.get("children", []):
        if children["source_id"] == actual_node:
            if len(r_levels) >= 1:
                return get_level_map(children, r_levels)
            else:
                return children


def remove_iframes(content):
    if content is not None:
        for iframe in content.find_all("iframe"):
            iframe.extract()


def get_confirm_token(response):
    for key, value in response.cookies.items():
        if key.startswith('download_warning'):
            return value
    return None


def save_response_content(response, destination):
    CHUNK_SIZE = 32768
    with open(destination, "wb") as f:
        for chunk in response.iter_content(CHUNK_SIZE):
            if chunk:
                f.write(chunk)
                f.flush()
