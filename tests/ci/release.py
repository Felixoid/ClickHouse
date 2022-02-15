#!/usr/bin/env python

# -
# TODO:
# - use particular commit for release tag
# - use context and roll-back changes on failure
# - improve logging

from contextlib import contextmanager
from typing import Optional
import argparse
import logging

from git_helper import commit
from version_helper import git, get_version_from_repo, ClickHouseVersion, VersionType


class Release:
    BIG = ("major", "minor")
    SMALL = ("patch",)

    def __init__(self, version: ClickHouseVersion):
        self._version = version
        self._git = version._git
        self._release_commit = ""

    def run(self, cmd: str, cwd: Optional[str] = None) -> str:
        logging.info("Running in directory %s, command:\n    %s", cwd or "$CWD", cmd)
        return self._git.run(cmd, cwd)

    @property
    def version(self) -> ClickHouseVersion:
        return self._version

    @version.setter
    def version(self, version: ClickHouseVersion):
        if not isinstance(version, ClickHouseVersion):
            raise ValueError(f"version must be ClickHouseVersion, not {type(version)}")
        self._version = version

    @property
    def release_commit(self) -> str:
        return self._release_commit

    @release_commit.setter
    def release_commit(self, release_commit: str):
        self._release_commit = commit(release_commit)

    def check_branch(self, release_type: str):
        if release_type in self.BIG:
            # Commit to spin up the release must belong to a main branch
            output = self.run(f"git branch --contains={self.release_commit} master")
            if "master" not in output:
                raise Exception(
                    f"commit {self.release_commit} must belong to 'master' for "
                    f"{release_type} release"
                )
        if release_type in self.SMALL:
            branch = f"{self.version.major}.{self.version.minor}"
            if self._git.branch != branch:
                raise Exception(f"branch must be '{branch}' for {release_type} release")

    def bump_version_part(self, release_type: str):
        self.version = self.version.update(release_type)

    def update(self):
        self._git.update()
        self.version = get_version_from_repo()

    @contextmanager
    def new_branch(self, name: str, start_point: str = ""):
        self.run(f"git branch {name} {start_point}")
        try:
            yield
        except BaseException:
            self.run(f"git branch -D {name}")
            raise

    @contextmanager
    def checkout(self, ref: str, with_rollback: bool = False):
        orig_ref = self._git.branch or self._git.sha
        need_rollback = False
        if ref not in (self._git.branch, self._git.sha):
            need_rollback = True
            self.run(f"git checkout {ref}")
        try:
            yield
        except BaseException:
            self.run(f"git checkout {orig_ref}")
            raise
        else:
            if with_rollback and need_rollback:
                self.run(f"git checkout {orig_ref}")

    @contextmanager
    def prestable(self, args: argparse.Namespace):
        # Create release branch
        release_branch = f"{self.version.major}.{self.version.minor}"
        with self.new_branch(release_branch, self.release_commit):
            with self.checkout(release_branch, True):
                self.update()
                self.version.with_description(VersionType.PRESTABLE)
                with self.publish_release(args):
                    # At this point everything will rollback automatically
                    yield

    @contextmanager
    def publish_release(self, args: argparse.Namespace):
        with self.create_tag(args):
            self.run(
                "gh release create --prerelease --draft "
                f"--repo {args.repo} '{self.version.describe}'"
            )
            try:
                yield
            except BaseException:
                self.run(
                    f"gh release delete --yes "
                    f"--repo {args.repo} '{self.version.describe}'"
                )
                raise

    @contextmanager
    def create_tag(self, args: argparse.Namespace):
        tag = self.version.describe
        self.run(f"git tag -a -m 'Release {tag}' '{tag}'")
        with self.push(f"'{tag}'", args):
            try:
                yield
            except BaseException:
                self.run(f"git tag -d '{tag}'")
                raise

    @contextmanager
    def push(self, ref: str, args: argparse.Namespace):
        self.run(f"git push git@github.com:{args.repo}.git {ref}")
        try:
            yield
        except BaseException:
            self.run(f"git push -d git@github.com:{args.repo}.git {ref}")
            raise

    def do(self, args: argparse.Namespace):
        if not args.no_check_dirty:
            logging.info("Checking if repo is clean")
            self.run("git diff HEAD --exit-code")

        self.release_commit = args.commit
        if not args.no_check_branch:
            self.check_branch(args.release_type)

        if args.release_type in self.BIG:
            with self.prestable(args):
                raise Exception("test rollback")
            # self.testing


#    def update_versions(self, release_type: str, versions: VERSIONS) -> VERSIONS:
#        # The only change to an old versions file is updating hash to the
#        # current commit
#        original_versions = versions
#        original_versions["VERSION_GITHASH"] = self.sha
#        original_versions["VERSION_STRING"] = (
#            f"{original_versions['VERSION_MAJOR']}."
#            f"{original_versions['VERSION_MINOR']}."
#            f"{original_versions['VERSION_PATCH']}."
#            f"{self.commits_since_tag}"
#        )
#        original_versions["VERSION_DESCRIBE"] = (
#            f"v{original_versions['VERSION_MAJOR']}."
#            f"{original_versions['VERSION_MINOR']}."
#            f"{original_versions['VERSION_PATCH']}."
#            f"{self.commits_since_tag}-prestable"
#        )
#
#        versions = original_versions.copy()
#        self.new_branch = f"{versions['VERSION_MAJOR']}.{versions['VERSION_MINOR']}"
#
#        tag_version, tag_type = self.latest_tag.split("-", maxsplit=1)
#        tag_parts = tag_version[1:].split(".")
#        if (
#            tag_type in ("prestable", "testing")
#            and tag_parts[0] == versions["VERSION_MAJOR"]
#            and tag_parts[1] == versions["VERSION_MINOR"]
#        ):
#            # changes are incremental for these releases
#            versions["changes"] = (
#                int(tag_version.split(".")[-1]) + self.commits_since_tag
#            )
#        else:
#            versions["changes"] = self.commits_since_tag
#
#        self.new_tag = (
#            "v{VERSION_MAJOR}.{VERSION_MINOR}.{VERSION_PATCH}.{changes}"
#            "-prestable".format_map(versions)
#        )
#
#        if release_type == "patch":
#            self.create_new_branch = False
#            versions["VERSION_PATCH"] = int(versions["VERSION_PATCH"]) + 1
#        elif release_type == "minor":
#            versions["VERSION_MINOR"] = int(versions["VERSION_MINOR"]) + 1
#            versions["VERSION_PATCH"] = 1
#        elif release_type == "major":
#            versions["VERSION_MAJOR"] = int(versions["VERSION_MAJOR"]) + 1
#            versions["VERSION_MINOR"] = 1
#            versions["VERSION_PATCH"] = 1
#        else:
#            raise ValueError(f"release type {release_type} is not known")
#
#        # Should it be updated for any release?..
#        versions["VERSION_STRING"] = (
#            f"{versions['VERSION_MAJOR']}."
#            f"{versions['VERSION_MINOR']}."
#            f"{versions['VERSION_PATCH']}.1"
#        )
#        versions["VERSION_REVISION"] = int(versions["VERSION_REVISION"]) + 1
#        versions["VERSION_GITHASH"] = self.sha
#        versions["VERSION_DESCRIBE"] = f"v{versions['VERSION_STRING']}-prestable"
#        return versions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Script to release a new ClickHouse version, requires `git` and "
        "`gh` (github-cli) commands",
    )

    parser.add_argument(
        "--repo",
        default="ClickHouse/ClickHouse",
        help="repository to create the release",
    )
    parser.add_argument(
        "--type",
        default="minor",
        # choices=Release.BIG+Release.SMALL, # add support later
        choices=Release.BIG + Release.SMALL,
        dest="release_type",
        help="a release type, new branch is created only for 'major' and 'minor'",
    )
    parser.add_argument(
        "--commit",
        default=git.sha,
        type=commit,
        help="commit create a release, default to HEAD",
    )
    parser.add_argument(
        "--no-check-dirty",
        action="store_true",
        help="skip check repository for uncommited changes",
    )
    parser.add_argument(
        "--no-check-branch",
        action="store_true",
        help="by default, 'major' and 'minor' types work only for master, and 'patch' "
        "works only for a release branches, that name should be the same as "
        "'$MAJOR.$MINOR' version, e.g. 22.2",
    )
    parser.add_argument(
        "--no-publish-release",
        action="store_true",
        help="by default, 'major' and 'minor' types work only for master, and 'patch' ",
    )

    return parser.parse_args()


def prestable():
    pass


def main():
    logging.basicConfig(level=logging.INFO)
    args = parse_args()
    release = Release(get_version_from_repo())

    release.do(args)

    # if not args.no_publish_release:
    #    # Publish release on github for the current HEAD (master, if checked)
    #    git.run(f"gh release create --draft {git.new_tag} --target {git.sha}")

    ## Commit updated versions to HEAD and push to remote
    # write_versions(versions_file, new_versions)
    # git.run(f"git checkout -b {git.new_branch}-helper")
    # git.run(
    #    f"git commit -m 'Auto version update to [{new_versions['VERSION_STRING']}] "
    #    f"[{new_versions['VERSION_REVISION']}]' {versions_file}"
    # )
    # git.run(f"git push -u origin {git.new_branch}-helper")
    # git.run(
    #    f"gh pr create --title 'Update version after release {git.new_branch}' "
    #    f"--body-file '{git.root}/.github/PULL_REQUEST_TEMPLATE.md'"
    # )

    ## Create a new branch from the previous commit and push there with creating
    ## a PR
    # git.run(f"git checkout -b {git.new_branch} HEAD~")
    # write_versions(versions_file, versions)
    # git.run(
    #    f"git commit -m 'Auto version update to [{versions['VERSION_STRING']}] "
    #    f"[{versions['VERSION_REVISION']}]' {versions_file}"
    # )
    # git.run(f"git push -u origin {git.new_branch}")
    # git.run(
    #    "gh pr create --title 'Release pull request for branch "
    #    f"{versions['VERSION_MAJOR']}.{versions['VERSION_MINOR']}' --body "
    #    "'This PullRequest is part of ClickHouse release cycle. It is used by CI "
    #    "system only. Do not perform any changes with it.' --label release"
    # )


if __name__ == "__main__":
    main()
