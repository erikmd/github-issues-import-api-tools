#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# JSON to GitHub Issues Importer for Python 3
# Written by Erik Martin-Dorel for migrating the PG issues
#
# Reuse code from Théo Zimmermann's Coq bug tracker migration script
# (https://gist.github.com/Zimmi48/d923e52f64fe17c72852d9c148bfcdc6/)
#
# Itself based on the "Bugzilla XML File to GitHub Issues Converter" by
# Andriy Berestovskyy (https://github.com/semihalf-berestovskyy-andriy/tools/)
#
# This script is licensed under the Apache 2.0 license.
#
# How to use the script:
#
# 1. Generate a GitHub access token:
#    - on GitHub select "Settings"
#    - select "Personal access tokens"
#    - click "Generate new token"
#    - type a token description, i.e. "json2github"
#    - select "public_repo" to access just public repositories
#    - save the generated token into the migration script
#
# 2. Export issues from repo-1 into a .json file:
# curl -f -i -X GET -H "Accept: application/json" "https://api.github.com/repos/username/repo-1/issues?state=all&sort=created&direction=asc" > page-1.txt
# tail -n+24 page-1.txt > issues.json # etc. (cat pages to a single JSON array)
#
# 3. Export issues comments from repo-1
# perl -wne 'if(m|comments",|) { s/^.*(https:.*comments)".*$/$1/; print; }' issues.json > URLs.txt
# export GITHUB_TOKEN="..."
# mkdir comments
# cat URLs.txt | xargs -L 1 bash -c 'URL="$1"; NUM=${URL%/comments}; NUM=${NUM##*/}; echo "Retrieving ${URL} ..."; curl -fsSL -X GET -H "Authorization: token ${GITHUB_TOKEN}" -H "Accept: application/json" -o "./comments/${NUM}.json" "${URL}"' bash
#
# 4. Run the migration script and check all the warnings:
# ./json2github.py -j issues.json -c ./comments/ -i 0 -o owner -r repo -t $GITHUB_TOKEN
#
# 5. Run the migration script again and force the updates:
# ./json2github.py -j issues.json -c ./comments/ -i 0 -o owner -r repo -t $GITHUB_TOKEN -f
#
# The script depends on the requests package.
# You can get the right environment by running:
# $ sudo pip3 install --upgrade pip && sudo pip3 install requests

import csv
import getopt
import json
import os
import re
import requests
import sys
import time

github_url = "https://api.github.com"
src_issues = []

# Default values
src_prefix_issues = ""
force_update = False
json_file = ""
comments_path = ""
github_owner = ""
github_repo = ""
github_token = ""
existing_issues = 0
# existing issues <=> issue numbers already taken in GitHub dest repo.
# this info is provided by CLI arg (the script can find this by itself
# but this will spare API requests.

# WARNING: each imported issue will have these extra labels associated
labels_to_add = ["pg: async"]

# Feel free to modify this
debug = False

issue_unused_fields = [
    "url",
    "repository_url",
    "labels_url",
    "comments_url",
    "events_url",
    "html_url",
    "id",
    "locked",
    "assignees",
    "milestone",
    "comments",
    "author_association",
]

# comment_unused_fields = [
#     "url",
#     "html_url",
#     "issue_url",
#     "id",
#     "updated_at",
#     "author_association",
# ]


def usage():
    print("Issues JSON file to GitHub Issues Uploader")
    print("Usage: \t%s [-h] [-f]\n"
          "\t[-j <src JSON file>] [-c <comments folder path>]\n"
          "\t[-p <src-user/src-repo>] (optional, if you want backlinks)\n"
          "\t[-i <existing issues>]\n"
          "\t[-o <dst GitHub owner>] [-r <dst repo>] [-t <dst access token>]\n"
          % os.path.basename(__file__))
    print("Example:")
    print("\t%s -h" % os.path.basename(__file__))
    print("\t%s -j issues.json -c ./comments/ -p src_user/src_repo \\\n"
          "\t\t-i 0 -o dst_login -r dst_repo -t dst_token"
          % os.path.basename(__file__))
    exit(1)


def is_strictly_sorted(l):
    return all(l[i] < l[i+1] for i in range(len(l)-1))


def id_convert(inp):
    id = int(inp)
    # Assume is_strictly_sorted(src_issues) and src_issues[0] >= 1
    if id not in src_issues:
        print("WARNING: %d doesn't belong in %s" % (id, src_issues))
        return 0  # dummy value
    already_imported = 0
    for cur in src_issues:
        if id == cur:
            return existing_issues + already_imported + 1
        else:
            already_imported += 1
    print("ERROR: In id_convert(%d): unexpected error" % id)
    exit(2)


def strid_convert_from_match(match):
    return match.group(1) + '#' + str(id_convert(match.group(2)))


# WARNING: this function is OK for PG's migration but it's actually
# incomplete as we'd also need to substitute owner-1/repo-1#1, etc.
def subst_comment_id(body):
    # Replace #1 with #238
    return re.sub(r'(^|\s)#(\d\d?\d?\d?)', strid_convert_from_match, body)

# TESTCASE
# existing_issues = 237
# src_issues = [1, 3, 4, 5, 6]
# body = "#1 l'issue #3;\n#4 l'issue #6\n #8 "
# print(body)
# print(subst_comment_id(body))
# exit(0)

# def subst_issuecomment(body):
#     global src_prefix_issues
#     # https://github.com/psteckler/ProofGeneral/issues/1#issuecomment-241012450
#     # ===> https://github.com/ProofGeneral/PG/issues/238
#     return body


def fields_ignore(obj, fields):
    for field in fields:
        obj.pop(field, None)


def fields_dump(obj):
    # Make sure we have converted all the fields
    for key, val in obj.items():
        print(" " * 8 + "%s[%d] = %s" % (key, len(val), val))


# def fields_filter(obj, fields):
#     ret = {}
#     for field in fields:
#         ret[field] = obj[field]
#     return ret


def extract_labels(labels):
    ret = []
    for labelobj in labels:
        ret.append(labelobj["name"])
    return ret


def comment_convert(comment):
    ret = []

    created_at = comment["created_at"]
    # updated_at = comment["updated_at"]
    body = comment["body"]
    login = comment["user"]["login"]

    ret.append("Comment author: @" + login)
    ret.append("")
    ret.append(subst_comment_id(body))

    return {"body": "\n".join(ret), "created_at": created_at}


def comments_convert(comments):
    ret = []
    if isinstance(comments, list):
        for comment in comments:
            ret.append(comment_convert(comment))
    else:
        ret.append(comment_convert(comments))

    return ret


def get_comments_convert(src_number, comments_path):
    with open(comments_path + str(src_number) + ".json") as json_data:
        comments_json = json.load(json_data)
    return comments_convert(comments_json)


def bug_convert(bug, comments_path):
    ret = {}
    ret["body"] = []
    ret["body"].append("Note: the issue was imported automatically using %s"
                       % os.path.basename(__file__))
    # No Need For ret["body"].append("")
    ret["comments"] = []
    ret["labels"] = []

    # Convert number
    src_number = bug.pop("number")
    ret["number"] = id_convert(src_number)
    # Set src_number (will be popped later)
    ret["src_number"] = src_number
    # Set comments (will be popped later)
    ret["comments"].extend(get_comments_convert(src_number, comments_path))
    # Convert labels
    ret["labels"].extend(extract_labels(bug.pop("labels")))
    ret["labels"].extend(labels_to_add)
    # Set title
    ret["title"] = bug.pop("title")
    # Set created_at
    ret["created_at"] = bug.pop("created_at")
    # Set updated_at
    ret["updated_at"] = bug.pop("updated_at")
    # Set closed
    state = bug.pop("state")
    ret["closed"] = (state == "closed")
    # WARNING: We only assign open bug reports
    assignee = bug.pop("assignee")
    if not ret["closed"] and assignee:
        ret["assignee"] = assignee
    closed_at = bug.pop("closed_at")
    if closed_at:
        ret["closed_at"] = closed_at

    # Extract login
    login = bug.pop("user")["login"]

    # Create the bug description
    if src_prefix_issues:
        text = "Original issue: %s#%d" % (src_prefix_issues, src_number)
    else:
        text = "Original issue number: %d" % src_number
    ret["body"].append(text)
    ret["body"].append("Opened by: @" + login)
    ret["body"].append("")
    ret["body"].append(subst_comment_id(bug.pop("body")))

    # Put everything together
    ret["body"] = "\n".join(ret["body"])

    # Ignore some bug fields
    fields_ignore(bug, issue_unused_fields)
    # Make sure we have converted all the fields
    if bug:
        print("WARNING: unconverted bug fields:")
        fields_dump(bug)

    return ret


def bugs_convert(src_issues_json, comments_path):
    global src_issues
    src_issues = []
    for issue in src_issues_json:
        src_issues.append(issue["number"])
    if src_issues == []:
        print("WARNING: no issue")
        exit(0)
    if not (is_strictly_sorted(src_issues) and src_issues[0] >= 1):
        print("ERROR: issues numbers %s not strictly increasing"
              % str(src_issues))
        exit(2)
    new_issues = {}
    for issue in src_issues_json:
        new_issue = bug_convert(issue, comments_path)
        new_id = new_issue["number"]
        new_issues[new_id] = new_issue
    return new_issues


def github_get(url, avs={}):
    if url[0] == "/":
        u = "%s%s" % (github_url, url)
    elif url.startswith("https://"):
        u = url
    elif url.startswith("http://"):
        u = url
    else:
        u = "%s/repos/%s/%s/%s" % (github_url, github_owner, github_repo, url)

    if debug:
        print("GET: " + u)

    avs["access_token"] = github_token
    return requests.get(u, params=avs)


def github_post(url, avs={}, fields=[]):
    if url[0] == "/":
        u = "%s%s" % (github_url, url)
    else:
        u = "%s/repos/%s/%s/%s" % (github_url, github_owner, github_repo, url)

    d = {}
    # Copy fields into the data
    for field in fields:
        if field not in avs:
            print("Error posting filed %s to %s" % (field, url))
            exit(1)
        d[field] = avs[field]

    if debug:
        print("POST: " + u)
        print("DATA: " + json.dumps(d))

    if force_update:
        return requests.post(u, params={"access_token": github_token},
                             data=json.dumps(d))
    else:
        if not github_post.warn:
            print("Skipping POST... (use -f to force updates)")
            github_post.warn = True
        return True


github_post.warn = False


def github_label_create(label):
    if not github_get("labels/" + label):
        print("\tcreating label '%s' on GitHub..." % label)
        r = github_post("labels", {
            "name": label,
            "color": "0"*6,
        }, ["name", "color"])
        if not r:
            print("Error creating label %s: %s" % (label, r.headers))
            exit(1)


def github_labels_check(issues):
    labels_set = set()
    for id in issues:
        for label in issues[id]["labels"]:
            labels_set.add(label)

    for label in labels_set:
        if github_get("labels/" + label):
            print("\tlabel '%s' exists on GitHub" % label)
        else:
            if force_update:
                github_label_create(label)
            else:
                print("WARNING: label '%s' does not exist on GitHub" % label)


def github_assignees_check(issues):
    a_set = set()
    for id in issues:
        if "assignee" in issues[id]:
            a_set.add(issues[id]["assignee"])

    for assignee in a_set:
        if not github_get("/users/" + assignee):
            print("Error checking user '%s' on GitHub" % assignee)
            exit(1)
        else:
            print("Assignee '%s' exists" % assignee)


def github_issue_exist(number):
    if github_get("issues/%d" % number):
        return True
    else:
        return False


def github_issue_get(number):
    req = github_get("issues/%d" % number)
    if not req:
        print("Error getting GitHub issue #%d: %s" % (number, req.headers))
        exit(1)

    return req.json()


def github_issue_append(new_id, issue):
    params = {"access_token": github_token}
    headers = {"Accept": "application/vnd.github.golden-comet-preview+json"}
    src_id = issue.pop("src_number", 0)
    print("\timporting %s#%d to #%d on GitHub..."
          % (src_prefix_issues, src_id, new_id))
    u = ("https://api.github.com/repos/%s/%s/import/issues"
         % (github_owner, github_repo))
    comments = issue.pop("comments", [])
    # We can't assign people which are not in the organization / collaborators on the repo
    if github_owner != "ProofGeneral":  # FIXME
        issue.pop("assignee", None)
    r = requests.post(u, params=params, headers=headers,
                      data=json.dumps({"issue": issue, "comments": comments}))
    if not r:
        print("Error importing issue on GitHub:\n%s" % r.text)
        print("For the record, here was the request:\n%s"
              % json.dumps({"issue": issue, "comments": comments}))
        exit(1)
    u = r.json()["url"]
    wait = 1
    r = False
    while not r or r.json()["status"] == "pending":
        time.sleep(wait)
        wait = 2 * wait
        r = requests.get(u, params=params, headers=headers)
    if not r.json()["status"] == "imported":
        print("Error importing issue on GitHub:\n%s" % r.text)
        exit(1)
    # The issue_url field of the answer should be of the form .../ISSUE_NUMBER
    # So it's easy to get the issue number, to check that it is what was expected
    result = re.match("https://api.github.com/repos/"
                      + github_owner + "/" + github_repo
                      + "/issues/(\d+)", r.json()["issue_url"])
    if not result:
        print("Error while parsing issue number:\n%s" % r.text)
    issue_number = result.group(1)
    if str(new_id) != issue_number:
        print("Error while comparing created id #%s and expected id #%d (for src_id #%d)"
              % (issue_number, new_id, src_id))
    with open("json2github.log", "a") as f:
        f.write("%d, %s\n" % (src_id, issue_number))
    return issue_number


# def github_issues_add(issues):
#     global existing_issues
#     postponed = {}
#     id = 0
#     while True:
#         id += 1
#         if id <= existing_issues or github_get("issues/%d" % id):
#             if id in issues:
#                 print("Issue #%d already exists, postponing..." % id)
#                 postponed[id] = issues.pop(id)
#         else:
#             if id in issues:
#                 todo_id = id
#                 issue = issues.pop(id)
#             else:
#                 if len(postponed) == 0:
#                     if len(issues) == 0:
#                         print("===> All done.")
#                         exit(0)
#                     else:
#                         print("Error: No more postponed issues.")
#                         exit(1)
#                 # Find the first postponed issue
#                 todo_id = sorted(postponed.keys())[0]
#                 issue = postponed.pop(todo_id)
#             if force_update:
#                 print("Creating issue #%d..." % id)
#                 github_issue_append(todo_id, issue)

def github_issues_add(issues):
    id = existing_issues
    while True:
        id += 1
        if github_get("issues/%d" % id):
            if id in issues:
                print("Issue #%d already exists, skipping..." % id)
        else:
            if id in issues:
                issue = issues.pop(id)
            else:
                if len(issues) == 0:
                    print("===> All done.")
                    exit(0)
                else:
                    print("Error: No pending issues found.")
                    exit(1)
            if force_update:
                print("Creating issue #%d..." % id)
                github_issue_append(id, issue)


def args_parse(argv):
    global force_update
    global github_owner, github_repo, github_token
    global json_file, comments_path, existing_issues, src_prefix_issues

    try:
        opts, args = getopt.getopt(argv, "hfo:r:t:j:c:i:p:")
    except getopt.GetoptError:
        usage()
    for opt, arg in opts:
        if opt == '-h':
            usage()
        elif opt == "-f":
            print("WARNING: the repo will be UPDATED! No backups, no undos!")
            print("Press Ctrl+C within next 5 seconds to cancel the update:")
            time.sleep(5)
            force_update = True
        elif opt == "-o":
            github_owner = arg
        elif opt == "-r":
            github_repo = arg
        elif opt == "-t":
            github_token = arg
        elif opt == "-j":
            json_file = arg
        elif opt == "-c":
            comments_path = arg
        elif opt == "-i":
            existing_issues = int(arg)
        elif opt == "-p":
            src_prefix_issues = arg

    # Check the arguments
    if (not (json_file and comments_path and
             github_owner and github_repo and github_token)):
        print("Missing argument(s):\n  "
              "please specify JSON file, comments path, "
              "GitHub owner, repo and token.\n")
        usage()


def main(argv):
    global existing_issues
    # Parse command line arguments
    args_parse(argv)
    print("===> Importing JSON data to GitHub Issues...")
    print("\tSource JSON file:   %s" % json_file)
    print("\tSrc. comments dir.:  %s" % comments_path)
    print("\tDest. GitHub owner: %s" % github_owner)
    print("\tDest. GitHub repo:  %s" % github_repo)

    with open(json_file) as json_data:
        src_issues_json = json.load(json_data)

    issues = bugs_convert(src_issues_json, comments_path)

    try:
        with open("json2github.log", "r") as f:
            print("===> Skipping already imported issues\n"
                  "(WARNING: this shouldn't happen when you run this script "
                  "for the first time)...")
            time.sleep(5)
            imported_bugs = csv.reader(f)
            for imported_bug in imported_bugs:
                issues.pop(int(imported_bug[0]), None)
                existing_issues = max(existing_issues, int(imported_bug[1]))
    except IOError:
        print("===> No log file found. Not skipping any issue.")

    print("===> Checking last existing issue actually exists.")
    if not github_issue_exist(existing_issues):
        print("Last existing issue doesn't actually exist. Aborting!")
        exit(1)
    print("===> Checking whether the following issue was created but not saved.")
    github_issue = github_get("issues/%d" % (existing_issues + 1))
    if github_issue:
        result = re.search("Original bug ID: BZ#(\d+)",
                           github_issue.json()["body"])
        if result:
            print("Indeed, this was the case.")
            src_id = int(result.group(1))
            issues.pop(src_id, None)
            with open("json2github.log", "a") as f:
                f.write("%d, %d\n" % (src_id, existing_issues + 1))

    print("===> Checking all the labels exist on GitHub...")
    github_labels_check(issues)
    print("===> Checking all the assignees exist on GitHub...")
    github_assignees_check(issues)

    # fake_issue = {"title": "Fake issue", "body": "Fake issue", "closed": True}
    # for i in xrange(1,existing_issues + 1):
    #     github_issue_append(0, fake_issue)

    # if debug:
    #     print("JSON (beware of size): " + json.dumps(issues))

    print("===> Adding issues on GitHub...")
    github_issues_add(issues)


if __name__ == "__main__":
    main(sys.argv[1:])
