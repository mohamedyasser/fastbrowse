import re
from dataclasses import dataclass

LOGIN_MARKERS = ("/login", "/authwall", "/checkpoint", "/uas/")
AGE = re.compile(r"^(\d+)\s*(s|m|h|d|w|mo|yr)$")
COUNT = re.compile(r"^([\d,]+)\s+(reaction|comment|repost)s?$")
FOLLOW_BUTTONS = {"Connect", "Follow", "Following", "Message"}
BODY_END = {"… more", "Show translation", "Like"}
SLUG = re.compile(r"^[\w%][\w%.\-]*$")
REACTED = re.compile(r"^(?:.+ and )?([\d,]+) others? reacted$")
FALLBACK_LIMIT = 2000


@dataclass
class Post:
    author: str
    headline: str
    age: str
    text: str
    reposted_by: str | None
    reactions: int
    comments: int


def is_login_wall(url):
    return any(marker in url for marker in LOGIN_MARKERS)


def profile_activity_url(value):
    match = re.search(r"linkedin\.com/in/([^/?#]+)", value)
    slug = match.group(1) if match else value.strip("/ ")
    if not SLUG.match(slug):
        raise ValueError(f"Not a LinkedIn profile slug or URL: {value!r}")
    return f"https://www.linkedin.com/in/{slug}/recent-activity/all/"


def parse_chunk(chunk):
    lines = [line.strip() for line in chunk.splitlines() if line.strip()]
    age_at = next((i for i, line in enumerate(lines[:14]) if AGE.match(re.sub(r"\s*•.*$", "", line))), None)
    if age_at is None:
        return None
    head = lines[:age_at]
    reposted_by = None
    if head and head[0].endswith(" reposted this"):
        reposted_by = head[0].removesuffix(" reposted this")
        head = head[1:]
    body, counts = [], {"reaction": 0, "comment": 0}
    collecting = True
    for line in lines[age_at + 1:]:
        found = COUNT.match(line)
        reacted = REACTED.match(line)
        if reacted:
            collecting = False
            counts["reaction"] = max(counts["reaction"], int(reacted.group(1).replace(",", "")) + 1)
        elif found:
            collecting = False
            if found.group(2) in counts:
                counts[found.group(2)] = int(found.group(1).replace(",", ""))
        elif collecting and line in BODY_END:
            collecting = False
        elif collecting and not (not body and line in FOLLOW_BUTTONS):
            body.append(line)
    return Post(
        author=head[0] if head else "",
        headline=head[-1] if len(head) > 1 else "",
        age=re.sub(r"\s*•.*$", "", lines[age_at]),
        text="\n".join(body),
        reposted_by=reposted_by,
        reactions=counts["reaction"],
        comments=counts["comment"],
    )


def parse_feed(text):
    chunks = re.split(r"(?m)^Feed post\s*$", text)[1:]
    return [post for post in map(parse_chunk, chunks) if post]


def parse_post(text):
    posts = parse_feed(text)
    if posts and posts[0].text:
        return posts[0].text
    return text.strip()[:FALLBACK_LIMIT]


def post_key(post):
    return (post.author, post.age, post.text[:80])
