#!/usr/bin/env python3
"""
GitHub PR Statistics Generator

This tool extracts and generates pull request statistics from GitHub repositories
according to the provided specification.
"""

import json
import csv
import requests
import time
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, asdict
from pathlib import Path
import argparse
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class Comment:
    """Represents a comment on a PR"""
    timestamp: str
    type: str  # review_comment, issue_comment, review_summary
    author: str
    comment_id: str

@dataclass
class PullRequest:
    """Represents a pull request"""
    created_at: str
    updated_at: str
    closed_at: str
    merged_at: str
    author: str
    number: str
    title: str

@dataclass
class PullRequestStats:
    """Represents statistics for a single pull request"""
    pr_meta: Dict[str, Any]
    # pr_number: int
    # title: str
    # author: str
    request_to_review_timestamp: Optional[str]
    pr_approved_timestamp: Optional[str]
    # comments_timestamps: Dict[str, Any]

    # update_timestamps: List[str]
    review_given_timestamp: Optional[str]
    # pr_merge_timestamp: Optional[str]
    # is_closed: bool
    reviews: List[Dict]
    # pr_comments: List[Dict]
    # issue_comments: List[Dict]
    timeline: List[Dict]
    # commits: List[Dict]


@dataclass
class RepositoryStats:
    """Represents complete statistics for a repository"""
    repository: Dict[str, str]
    generated_at: str
    pull_requests: List[PullRequestStats]


class GitHubAPIClient:
    """GitHub API client with rate limiting and error handling"""

    def __init__(self, token: str):
        self.token = token
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'token {token}',
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'GitHub-PR-Stats-Generator'
        })
        self.base_url = 'https://api.github.com'

    def _make_request(self, url: str, params: Dict = None) -> Dict:
        """Make a request with rate limiting and error handling"""
        while True:
            response = self.session.get(url, params=params)

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 403:
                # Rate limited
                reset_time = int(response.headers.get('X-RateLimit-Reset', 0))
                current_time = int(time.time())
                sleep_time = max(reset_time - current_time + 60, 60)
                logger.warning(f"Rate limited. Sleeping for {sleep_time} seconds")
                time.sleep(sleep_time)
            elif response.status_code == 404:
                logger.error(f"Resource not found: {url}")
                return {}
            else:
                response.raise_for_status()

    def _paginate(self, url: str, params: Dict = None) -> List[Dict]:
        """Handle paginated responses"""
        results = []
        page = 1
        params = params or {}

        while True:
            params['page'] = page
            params['per_page'] = 100

            data = self._make_request(url, params)

            if not data or not isinstance(data, list):
                break

            results.extend(data)

            if len(data) < 100:  # Last page
                break

            page += 1

        return results

    def get_pull_requests(self, owner: str, repo: str, state: str = 'all') -> List[Dict]:
        """Get all pull requests for a repository"""
        url = f'{self.base_url}/repos/{owner}/{repo}/pulls'
        return self._paginate(url, {'state': state})

    def get_pr_reviews(self, owner: str, repo: str, pr_number: int) -> List[Dict]:
        """Get reviews for a specific pull request"""
        url = f'{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}/reviews'
        return self._paginate(url)

    def get_pr_comments(self, owner: str, repo: str, pr_number: int) -> List[Dict]:
        """Get review comments for a specific pull request"""
        url = f'{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}/comments'
        return self._paginate(url)

    def get_issue_comments(self, owner: str, repo: str, issue_number: int) -> List[Dict]:
        """Get issue comments for a specific pull request"""
        url = f'{self.base_url}/repos/{owner}/{repo}/issues/{issue_number}/comments'
        return self._paginate(url)

    def get_pr_timeline(self, owner: str, repo: str, issue_number: int) -> List[Dict]:
        """Get timeline events for a pull request"""
        url = f'{self.base_url}/repos/{owner}/{repo}/issues/{issue_number}/timeline'
        # Timeline API requires special accept header
        headers = {'Accept': 'application/vnd.github.mockingbird-preview+json'}

        response = self.session.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
        return []

    def get_pr_commits(self, owner: str, repo: str, pr_number: int) -> List[Dict]:
        """Get commits for a specific pull request"""
        url = f'{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}/commits'
        return self._paginate(url)


class PRStatsGenerator:
    """Main class for generating PR statistics"""

    def __init__(self, token: str):
        self.client = GitHubAPIClient(token)

    def _get_request_to_review_timestamp(self, pr: Dict, timeline: List[Dict]) -> Optional[str]:
        """Extract the timestamp when PR was marked ready for review"""
        # If PR was created as ready for review (not draft)
        if not pr.get('draft', False):
            return pr['created_at']

        # Look for ready_for_review or review_requested events in timeline
        for event in timeline:
            if event.get('event') in ['ready_for_review', 'review_requested']:
                return event.get('created_at')

        return pr['created_at']

    def _get_approval_timestamp(self, reviews: List[Dict]) -> Optional[str]:
        """Get the first approval timestamp"""
        approved_reviews = [r for r in reviews if r.get('state') == 'APPROVED']
        if approved_reviews:
            return min(approved_reviews, key=lambda x: x['submitted_at'])['submitted_at']
        return None

    def _get_review_given_timestamp(self, reviews: List[Dict]) -> Optional[str]:
        """Get timestamp of first substantive review (not just approval)"""
        substantive_reviews = [
            r for r in reviews
            if r.get('state') in ['REQUEST_CHANGES', 'COMMENT'] or
               (r.get('state') == 'APPROVED' and r.get('body'))
        ]
        if substantive_reviews:
            return min(substantive_reviews, key=lambda x: x['submitted_at'])['submitted_at']
        return None

    def _collect_comments(self, pr_author: str, reviews: List[Dict],
                          pr_comments: List[Dict], issue_comments: List[Dict]) -> Dict[str, Any]:
        """Collect all comments with metadata"""
        comments = []

        # Review comments (inline code comments)
        for comment in pr_comments:
            if comment['user']['login'] != pr_author:
                comments.append(Comment(
                    timestamp=comment['created_at'],
                    type='review_comment',
                    author=comment['user']['login'],
                    comment_id=str(comment['id'])
                ))

        # Issue comments
        for comment in issue_comments:
            if comment['user']['login'] != pr_author:
                comments.append(Comment(
                    timestamp=comment['created_at'],
                    type='issue_comment',
                    author=comment['user']['login'],
                    comment_id=str(comment['id'])
                ))

        # Review summary comments
        for review in reviews:
            if review['user']['login'] != pr_author and review.get('body'):
                comments.append(Comment(
                    timestamp=review['submitted_at'],
                    type='review_summary',
                    author=review['user']['login'],
                    comment_id=str(review['id'])
                ))

        # Sort comments by timestamp
        comments.sort(key=lambda x: x.timestamp)

        return {
            'total_comments': len(comments),
            'comments': [asdict(comment) for comment in comments]
        }

    def _get_update_timestamps(self, commits: List[Dict]) -> List[str]:
        """Get timestamps of all commits (updates) to the PR"""
        # Filter out merge commits and sort by date
        regular_commits = [
            commit for commit in commits
            if len(commit.get('parents', [])) <= 1  # Not a merge commit
        ]

        timestamps = [commit['commit']['author']['date'] for commit in regular_commits]
        return sorted(timestamps)

    def get_timeline_stat(self, timeline_event: Dict):
        actor = timeline_event.get('actor', {}).get('login')
        author = timeline_event.get('author', {}).get('name')
        return {
            'event': timeline_event.get('event'),
            'author': actor or author,
            'created_at': timeline_event.get('created_at', timeline_event.get('author', {}).get('date')),
        }

    def get_review_stat(self, review_event: Dict):
        return {
            'state': review_event.get('state'),
            'created_at': review_event.get('submitted_at'),
            'author': review_event.get('user', {}).get('login')
        }

    def generate_pr_stats(self, pr: Dict, owner: str, repo: str) -> PullRequestStats:
        """Generate statistics for a single pull request"""
        pr_number = pr['number']
        logger.info(f"Processing PR #{pr_number}: {pr['title'][:50]}...")

        # Fetch additional data
        raw_reviews = self.client.get_pr_reviews(owner, repo, pr_number)
        reviews = [
            self.get_review_stat(review_event)
            for review_event in
            raw_reviews
        ]
        raw_timeline = self.client.get_pr_timeline(owner, repo, pr_number)
        # pr_comments = self.client.get_pr_comments(owner, repo, pr_number)
        # issue_comments = self.client.get_issue_comments(owner, repo, pr_number)
        timeline = [
            self.get_timeline_stat(timeline_event) for timeline_event in
            raw_timeline
        ]
        # commits = self.client.get_pr_commits(owner, repo, pr_number)

        # Extract statistics
        request_to_review = self._get_request_to_review_timestamp(pr, raw_timeline)
        approval_timestamp = self._get_approval_timestamp(raw_reviews)
        review_given_timestamp = self._get_review_given_timestamp(raw_reviews)
        # comments_data = self._collect_comments(
        #     pr['user']['login'], reviews, pr_comments, issue_comments
        # )
        # update_timestamps = self._get_update_timestamps(commits)

        return PullRequestStats(
            pr_meta=PullRequest(
                created_at=pr['created_at'],
                updated_at=pr['updated_at'],
                closed_at=pr['closed_at'],
                merged_at=pr['merged_at'],
                author=pr['user']['login'],
                number=pr['number'],
                title=pr['title'],
            ),
            request_to_review_timestamp=request_to_review,
            pr_approved_timestamp=approval_timestamp,
            review_given_timestamp=review_given_timestamp,
            reviews=reviews,
            timeline=timeline
        )

    def generate_stats(self, repo_spec: str,
                       date_from: Optional[str] = None,
                       date_to: Optional[str] = None,
                       author: Optional[str] = None,
                       output_file: Optional[str] = None) -> RepositoryStats:
        """Generate statistics for a repository"""
        owner, repo = repo_spec.split('/')
        logger.info(f"Generating stats for {owner}/{repo}")

        # Fetch all pull requests
        prs = self.client.get_pull_requests(owner, repo)
        logger.info(f"Found {len(prs)} pull requests")

        # Apply filters
        # if date_from:
        #     prs = [pr for pr in prs if pr['created_at'] >= date_from]
        # if date_to:
        #     prs = [pr for pr in prs if pr['created_at'] <= date_to]
        # if author:
        #     prs = [pr for pr in prs if pr['user']['login'] == author]

        logger.info(f"Processing {len(prs)} pull requests after filtering")

        # Generate stats for each PR
        pr_stats = []
        self._init_json_output(output_file, {})
        for pr in prs:
            try:
                stats = self.generate_pr_stats(pr, owner, repo)
                self._append_pr_to_json(output_file, stats)
                pr_stats.append(stats)
            except Exception as e:
                logger.error(f"Error processing PR #{pr['number']}: {e}")
                continue

        return RepositoryStats(
            repository={
                'name': repo,
                'owner': owner,
                'url': f'https://github.com/{owner}/{repo}'
            },
            generated_at=datetime.now(timezone.utc).isoformat(),
            pull_requests=pr_stats
        )

    def _init_json_output(self, output_file: str, repo_info: Dict[str, str]):
        """Initialize JSON output file with metadata"""
        initial_data = {
            "repository": repo_info,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "pull_requests": []
        }
        with open(output_file, 'w') as f:
            json.dump(initial_data, f, indent=2)

    def _append_pr_to_json(self, output_file: str, pr_stats: PullRequestStats):
        """Append a PR's stats to the JSON file"""
        # Read existing data
        with open(output_file, 'r') as f:
            data = json.load(f)

        # Append new PR
        data['pull_requests'].append(asdict(pr_stats))

        # Write back
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)

    def export_json(self, stats: RepositoryStats, output_file: str):
        """Export statistics to JSON format"""
        with open(output_file, 'w') as f:
            json.dump(asdict(stats), f, indent=2)
        logger.info(f"Exported JSON to {output_file}")

    def export_csv(self, stats: RepositoryStats, output_file: str):
        """Export statistics to CSV format"""
        with open(output_file, 'w', newline='') as f:
            writer = csv.writer(f)

            # Write header
            writer.writerow([
                'pr_number', 'title', 'author', 'created_at',
                'request_to_review_timestamp', 'pr_approved_timestamp',
                'review_given_timestamp', 'pr_merge_timestamp', 'is_closed',
                'total_comments', 'total_updates'
            ])

            # Write data
            for pr in stats.pull_requests:
                writer.writerow([
                    pr.pr_number,
                    pr.title,
                    pr.author,
                    pr.created_at,
                    pr.request_to_review_timestamp,
                    pr.pr_approved_timestamp,
                    pr.review_given_timestamp,
                    pr.pr_merge_timestamp,
                    pr.is_closed,
                    pr.comments_timestamps['total_comments'],
                    len(pr.update_timestamps)
                ])

        logger.info(f"Exported CSV to {output_file}")


def main():
    parser = argparse.ArgumentParser(description='Generate GitHub PR statistics')
    parser.add_argument('--repo', default='AdaptiveInsurance/AdaptiveBackend',
                        help='Repository in format owner/repo')
    parser.add_argument('--token',
                        default='',
                        help='GitHub personal access token')
    parser.add_argument('--output', default='pr_stats.json', help='Output file name')
    parser.add_argument('--format', choices=['json', 'csv'], default='json', help='Output format')
    parser.add_argument('--from', dest='date_from', help='Filter PRs from date (YYYY-MM-DD)')
    parser.add_argument('--to', dest='date_to', help='Filter PRs to date (YYYY-MM-DD)')

    args = parser.parse_args()

    # Convert date formats if provided
    date_from = f"{args.date_from}T00:00:00Z" if args.date_from else None
    date_to = f"{args.date_to}T23:59:59Z" if args.date_to else None

    # Generate statistics
    generator = PRStatsGenerator(args.token)
    stats = generator.generate_stats(
        args.repo,
        date_from=date_from,
        date_to=date_to,
        output_file=args.output,
    )

    # Export results
    # if args.format == 'json':
    #     generator.export_json(stats, args.output)
    # elif args.format == 'csv':
    #     generator.export_csv(stats, args.output)

    logger.info(f"Generated statistics for {len(stats.pull_requests)} pull requests")


if __name__ == '__main__':
    main()
