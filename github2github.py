#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copy GitHub Issues between repos/owners
# by Andriy Berestovskyy
#
# Adapted by Erik Martin-Dorel to support JSON import
#
# To generate a GitHub access token:
#    - on GitHub select "Settings"
#    - select "Personal access tokens"
#    - click "Generate new token"
#    - type a token description, i.e. "bugzilla2issues"
#    - select "public_repo" to access just public repositories
#    - save the generated token into the migration script
#

import json
import getopt
import os
import pprint
import re
import requests
import sys
import time

reload(sys)
sys.setdefaultencoding('utf-8')

force_update = False
github_url = "https://api.github.com"
src_github_owner = ""
src_github_repo = ""
src_github_token = ""

dst_github_owner = ""
dst_github_repo = ""
dst_github_token = ""

json_file = ""
comments_path = ""

existingIssues = 0


def usage():
    print "Copy GitHub Issues between repos/owners"
    print "Usage: \t%s [-h] [-f]\n" \
        "\t[ [-j <JSON file>] [-c <comments folder>] |\n" \
        "\t  [-O <src GitHub owner>] [-R <src repo>] [-T <src access token>] ]\n" \
        "\t[-i <existingIssues>]\n" \
        "\t[-o <dst GitHub owner>] [-r <dst repo>] [-t <dst access token>]\n" \
            % os.path.basename(__file__)
    print "Example:"
    print "\t%s -h" % os.path.basename(__file__)
    print "\t%s -j issues.json -c ./comments/ -i 0 \\\n" \
            "\t\t-o dst_login -r dst_repo -t dst_token" % os.path.basename(__file__)
    exit(1)


def src_github_get(url, avs = {}):
    global github_url, src_github_owner, src_github_repo, src_github_token

    if url[0] == "/":
        u = "%s%s" % (github_url, url)
    elif url.startswith("https://"):
        u = url
    elif url.startswith("http://"):
        u = url
    else:
        u = "%s/repos/%s/%s/%s" % (github_url, src_github_owner, src_github_repo, url)

    # TODO: debug
    # print "SRC GET: " + u

    avs["access_token"] = src_github_token
    return requests.get(u, params = avs)


def dst_github_get(url, avs = {}):
    global github_url, dst_github_owner, dst_github_repo, dst_github_token

    if url[0] == "/":
        u = "%s%s" % (github_url, url)
    elif url.startswith("https://"):
        u = url
    elif url.startswith("http://"):
        u = url
    else:
        u = "%s/repos/%s/%s/%s" % (github_url, dst_github_owner, dst_github_repo, url)

    # TODO: debug
    # print "DST GET: " + u

    avs["access_token"] = dst_github_token
    return requests.get(u, params = avs)


def dst_github_post(url, avs = {}, fields = []):
    global force_update
    global github_url, dst_github_owner, dst_github_repo, dst_github_token

    if url[0] == "/":
        u = "%s%s" % (github_url, url)
    else:
        u = "%s/repos/%s/%s/%s" % (github_url, dst_github_owner, dst_github_repo, url)

    d = {}
    # Copy fields into the data
    for field in fields:
        if field not in avs:
            print "Error posting filed %s to %s" % (field, url)
            exit(1)
        d[field] = avs[field]

    # TODO: debug
    # print "DST POST: " + u
    # print "DST DATA: " + json.dumps(d)

    if force_update:
        return requests.post(u, params = { "access_token": dst_github_token },
                                data = json.dumps(d))
    else:
        if not dst_github_post.warn:
            print "Skipping POST... (use -f to force updates)"
            dst_github_post.warn = True
        return True

dst_github_post.warn = False


def dst_github_issue_exist(number):
    if dst_github_get("issues/%d" % number):
        return True
    else:
        return False


def dst_github_issue_update(issue):
    id = issue["number"]

    print "\tupdating issue #%d on GitHub..." % id
    r = dst_github_post("issues/%d" % id, issue,
            ["title", "body", "state", "labels", "assignees"])
    if not r:
        print "Error updating issue #%d on GitHub:\n%s" % (id, r.headers)
        exit(1)


def dst_github_issue_append(issue):
    print "\tappending a new issue on GitHub..."
    r = dst_github_post("issues", issue, ["title", "body", "labels", "assignees"])
    if not r:
        print "Error appending an issue on GitHub:\n%s" % r.headers
        exit(1)
    return r


def check_issues_json():
    global json_file, comments_path

    with open(json_file) as json_data:
        issues = json.load(json_data)

    id0 = int(issues[0]["number"])
    idSpec = id0
    for issue in issues:
        idLook = int(issue["number"])
        pathToCheck = comments_path + str(idLook) + ".json"
        if not os.path.isfile(pathToCheck):
            print "File '%s' not found" % pathToCheck
            exit(1)
        if idSpec == idLook:
            idSpec += 1
        else:
            print "Non consecutive source issue numbers (%d, %d)" % (idSpec - 1, idLook)
            exit(1)


def fix_numbers_issue(issues, correspondance, ignored_pulls):
    
    
            
def github_issues_import():
    global existingIssues, force_update, json_file, comments_path

    correspondance = {}
    ignored_pulls = []

    def debug():
        print "correspondance:"; print correspondance
        print "ignored pulls:"; print ignored_pulls

    with open(json_file) as json_data:
        issues = json.load(json_data)

    idSrc = int(issues[0]["number"])
    idDst = existingIssues + 1
    for issue in issues:
        print "Processing issue #%d..." % idSrc
        if issue["pull_request"]:
            print "Skipping issue #%d which is a pull_request." % idSrc
            ignored_pulls.append(idSrc)
            idSrc += 1
            # idDst is kept as is
        else:
            if dst_github_issue_exist(idDst):
                if force_update:
                    dst_github_issue_update(issue)
                else:
                    print "\tupdating issue #%d... (dry-run)" % idDst
            else:
                if force_update:
                    print "\tfrom issue #%d, adding new issue #%d..." % (idSrc, idDst)
                    # Make sure the previous issue already exist
                    if idDst > 1 and not dst_github_issue_exist(idDst - 1):
                        print "Error adding issue #%d: previous issue does not exists" \
                                % idDst
                        debug()
                        exit(1)
                    req = dst_github_issue_append(issue)
                    new_issue = dst_github_get(req.headers["location"]).json()
                    if new_issue["number"] != idDst:
                        print "Error adding issue #%d: assigned unexpected issue id #%d" \
                            % (idDst, new_issue["number"])
                        debug()
                        exit(1)
                    # Update issue state
                    if issue["state"] != "open":
                        print "\tupdating-to-close issue #%d..." % idDst
                        new_issue["state"] = issue["state"]
                        dst_github_issue_update(new_issue)
                else:
                    print "\tfrom issue #%d, adding new issue #%d... (dry-run)" % (idSrc, idDst)
            correspondance[idSrc] = idDst
            idSrc += 1
            idDst += 1
    debug()

def github_issues_copy():
    id = 0
    while True:
        id += 1
        print "Copying issue #%d..." % id
        issue = src_github_get("issues/%d" % id)
        if issue:
            issue = issue.json()
            if dst_github_issue_exist(id):
                if force_update:
                    dst_github_issue_update(issue)
                else:
                    print "\tupdating issue #%d..." % id
            else:
                if force_update:
                    # Make sure the previous issue already exist
                    if id > 1 and not dst_github_issue_exist(id - 1):
                        print "Error adding issue #%d: previous issue does not exists" \
                                % id
                        exit(1)
                    req = dst_github_issue_append(issue)
                    new_issue = dst_github_get(req.headers["location"]).json()
                    if new_issue["number"] != id:
                        print "Error adding issue #%d: assigned unexpected issue id #%d" \
                            % (id, new_issue["number"])
                        exit(1)
                    # Update issue state
                    if issue["state"] != "open":
                        dst_github_issue_update(issue)
                else:
                    print "\tadding new issue #%d..." % id
        else:
            print "Done."
            break


def args_parse(argv):
    global force_update
    global src_github_owner, src_github_repo, src_github_token
    global dst_github_owner, dst_github_repo, dst_github_token
    global json_file, comments_path, existingIssues

    try:
        opts, args = getopt.getopt(argv,"hfo:r:t:O:R:T:j:c:i:")
    except getopt.GetoptError:
        usage()
    for opt, arg in opts:
        if opt == '-h':
            usage()
        elif opt == "-f":
            print "WARNING: the repo will be UPDATED! No backups, no undos!"
            print "Press Ctrl+C within next 5 secons to cancel the update:"
            time.sleep(5)
            force_update = True
        elif opt == "-o":
            dst_github_owner = arg
        elif opt == "-r":
            dst_github_repo = arg
        elif opt == "-t":
            dst_github_token = arg
            if not src_github_token:
                src_github_token = arg
        elif opt == "-O":
            src_github_owner = arg
        elif opt == "-R":
            src_github_repo = arg
        elif opt == "-T":
            src_github_token = arg
            if not dst_github_token:
                dst_github_token = arg
        elif opt == "-j":
            json_file = arg
        elif opt == "-c":
            comments_path = arg
        elif opt == "-i":
            existingIssues = int(arg)

    # Check the arguments
    if (not ((json_file and comments_path or
              src_github_owner and src_github_repo and src_github_token)
             and dst_github_owner and dst_github_repo and dst_github_token)):
        print("Error parsing arguments: please specify:\n"
              "1. (a) source JSON and comments folder path\n"
              "   (b) or source GitHub owner, repo and token\n"
              "2. and destination GitHub owner, repo and token\n")
        usage()


def main(argv):
    global src_github_owner, src_github_repo
    global dst_github_owner, dst_github_repo

    # Parse command line arguments
    args_parse(argv)
    print "===> Copying GitHub Issues between repos/owners..."
    if json_file:
        print "\tsource JSON file:    %s" % json_file
        print "\tsource comments:     %s" % comments_path
    else:
        print "\tsource GitHub owner: %s" % src_github_owner
        print "\tsource GitHub repo:  %s" % src_github_repo
    print "\tnum. of existing issues: %s" % existingIssues
    print "\tdest.  GitHub owner: %s" % dst_github_owner
    print "\tdest.  GitHub repo:  %s" % dst_github_repo

    if json_file:
        check_issues_json()
        github_issues_import()
    else:
        github_issues_copy()


if __name__ == "__main__":
    main(sys.argv[1:])
