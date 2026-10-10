
# --rawfile plus fromjson, not --slurpfile: slurpfile hands back the
# file contents already parsed, and whether that is the array itself
# or the array wrapped in another depends on what the file holds.
# Indexing it as `$releases[0][]` therefore iterated the values of a
# single release object - all strings - and failed with "Cannot index
# string with string tag_name". Raw text is parsed here instead, so
# the shape is known rather than assumed.
def arr: ((fromjson? // []) | if type == "array" then . else [] end);

# Release bodies arrive as HTML; flatten to text so the page can
# inject it safely. script/style blocks are dropped whole before the
# tags are stripped, so their contents do not survive as text - this
# matches what scripts/build_cache.py does locally. A handful of
# entities are decoded because jq has no HTML parser.
def text: (gsub("<script[^>]*>[\\s\\S]*?</script>"; " ")
           | gsub("<style[^>]*>[\\s\\S]*?</style>"; " ")
           | gsub("<[^>]*>"; " ")
           | gsub("&amp;"; "&")
           | gsub("&lt;"; "<")
           | gsub("&gt;"; ">")
           | gsub("&quot;"; "\"")
           | gsub("&#39;"; "\u0027")
           | gsub("&nbsp;"; " ")
           | gsub("[ \\t]+"; " ")
           | gsub("\\n[ \\t]+"; "\n")
           | sub("^\\s+"; "")
           | sub("\\s+$"; ""));

($releases | arr) as $rel
| ($commits | arr) as $com
| [ $rel[]
  | select(type == "object")
  | select(.draft != true)
  | select((.tag_name // "") | test("^v?[0-9]"))
  | {
      tag: .tag_name,
      version: (.tag_name | ltrimstr("v")),
      name: (.name // ""),
      published: (.published_at // ""),
      url: (.html_url // ""),
      prerelease: (.prerelease // false),
      body: ((.body // "") | text)
    }
] as $out_releases
| [ $com[]
  | {
      sha: ((.sha // "")[0:7]),
      subject: (((.commit // {}).message // "") | split("\n")[0]),
      date: (((.commit // {}).author // {}).date // ""),
      url: (.html_url // "")
    }
] as $out_commits            | {
    source: "rest",
    repo: "agniveshtm/flux",
    fetchedAt: $fetchedAt,
    latest: (($out_releases[0].version) // ""),
    releases: $out_releases,
    commits: $out_commits
  }