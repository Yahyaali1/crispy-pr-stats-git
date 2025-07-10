# GitHub PR Statistics Generation Specification

## Overview
This specification defines the requirements for extracting and generating pull request (PR) statistics from GitHub repositories. The system will collect timestamped events for each PR to enable analysis of development workflow efficiency and team performance.

## Data Requirements

### Per Pull Request Statistics
For each pull request in the repository, the following data points must be collected:

#### 1. Request to PR Review
- **Field Name**: `request_to_review_timestamp`
- **Data Type**: ISO 8601 timestamp
- **Description**: Timestamp when the PR was marked as "ready for review" or when review was explicitly requested
- **GitHub API Source**: 
  - PR creation timestamp if created as ready for review
  - Timeline events for "ready_for_review" or "review_requested" events
- **Special Cases**: 
  - Draft PRs: Use the timestamp when converted from draft to ready
  - Auto-requested reviews: Use the timestamp of the review request event

#### 2. PR Approved
- **Field Name**: `pr_approved_timestamp`
- **Data Type**: ISO 8601 timestamp
- **Description**: Timestamp of the first approval review
- **GitHub API Source**: Reviews API filtering for "APPROVED" state
- **Special Cases**: 
  - Multiple approvals: Record the first approval timestamp
  - Re-approval after changes: Record the final approval timestamp

#### 3. Comments
- **Field Name**: `comments_timestamps`
- **Data Type**: Array of objects containing timestamp and comment metadata
- **Description**: All comment timestamps including review comments, issue comments, and inline code comments
- **GitHub API Source**: 
  - Issue comments API
  - Review comments API
  - Pull request reviews API
- **Structure**:
  ```json
  {
    "timestamp": "2024-01-15T10:30:00Z",
    "type": "review_comment|issue_comment|review_summary",
    "author": "username",
    "comment_id": "123456789"
  }
  ```

#### 4. Update Timestamps
- **Field Name**: `update_timestamps`
- **Data Type**: Array of ISO 8601 timestamps
- **Description**: Timestamps of all commits pushed to the PR branch
- **GitHub API Source**: 
  - Commits API for the PR branch
  - Timeline events for "committed" events
- **Special Cases**: 
  - Force pushes: Include all push events
  - Merge commits: Exclude merge commits from main/master branch

#### 5. Review Given
- **Field Name**: `review_given_timestamp`
- **Data Type**: ISO 8601 timestamp
- **Description**: Timestamp when the first substantive review was provided (not just approval)
- **GitHub API Source**: Reviews API filtering for reviews with body content or line comments
- **Special Cases**: 
  - Distinguish between approval-only reviews and reviews with feedback
  - Include "REQUEST_CHANGES" and "COMMENT" review types

#### 6. PR Merge
- **Field Name**: `pr_merge_timestamp`
- **Data Type**: ISO 8601 timestamp (nullable)
- **Description**: Timestamp when the PR was merged into the target branch
- **GitHub API Source**: Pull request merged_at field
- **Special Cases**: 
  - Null if PR was never merged
  - Record actual merge timestamp, not close timestamp

#### 7. Close PR Flag
- **Field Name**: `is_closed`
- **Data Type**: Boolean
- **Description**: Flag indicating if the PR was closed without merging
- **GitHub API Source**: Pull request state and merged fields
- **Logic**: `true` if state is "closed" and merged is `false`

## Data Schema

### Output Format
```json
{
  "repository": {
    "name": "repo-name",
    "owner": "owner-name",
    "url": "https://github.com/owner/repo"
  },
  "generated_at": "2024-01-15T12:00:00Z",
  "pull_requests": [
    {
      "pr_number": 123,
      "title": "Feature: Add new functionality",
      "author": "username",
      "created_at": "2024-01-10T09:00:00Z",
      "request_to_review_timestamp": "2024-01-10T09:00:00Z",
      "pr_approved_timestamp": "2024-01-12T14:30:00Z",
      "comments_timestamps": [
        {
          "timestamp": "2024-01-11T10:15:00Z",
          "type": "review_comment",
          "author": "reviewer1",
          "comment_id": "987654321"
        }
      ],
      "update_timestamps": [
        "2024-01-10T09:00:00Z",
        "2024-01-11T16:45:00Z"
      ],
      "review_given_timestamp": "2024-01-11T10:15:00Z",
      "pr_merge_timestamp": "2024-01-12T15:00:00Z",
      "is_closed": false
    }
  ]
}
```

## API Requirements

### GitHub API Endpoints
1. **Pull Requests**: `/repos/{owner}/{repo}/pulls`
2. **Pull Request Reviews**: `/repos/{owner}/{repo}/pulls/{pull_number}/reviews`
3. **Issue Comments**: `/repos/{owner}/{repo}/issues/{issue_number}/comments`
4. **Review Comments**: `/repos/{owner}/{repo}/pulls/{pull_number}/comments`
5. **Timeline Events**: `/repos/{owner}/{repo}/issues/{issue_number}/timeline`
6. **Commits**: `/repos/{owner}/{repo}/pulls/{pull_number}/commits`

### Authentication
- Requires GitHub Personal Access Token or GitHub App authentication
- Minimum required scopes: `repo` (for private repositories) or `public_repo` (for public repositories)

### Rate Limiting
- Respect GitHub API rate limits (5000 requests/hour for authenticated users)
- Implement exponential backoff for rate limit handling
- Consider using GraphQL API for more efficient data retrieval

## Implementation Considerations

### Performance Optimization
- Use pagination for repositories with many PRs
- Implement caching for frequently accessed data
- Consider incremental updates for large repositories
- Use GraphQL API to reduce API calls when possible

### Error Handling
- Handle cases where PRs are deleted or inaccessible
- Manage API rate limiting gracefully
- Provide fallback values for missing timestamps
- Log errors for debugging and monitoring

### Data Validation
- Validate timestamp formats
- Ensure logical ordering of events (e.g., approval cannot precede creation)
- Handle timezone conversions consistently
- Validate PR state consistency

### Filtering Options
- Date range filtering for PR creation/merge dates
- Author filtering
- Branch filtering
- PR state filtering (open/closed/merged)
- Label-based filtering

## Output Formats

### Supported Export Formats
1. **JSON**: Complete data with all metadata
2. **CSV**: Flattened format for analysis tools
3. **Excel**: Formatted spreadsheet with multiple sheets
4. **Database**: Direct insertion into SQL databases

### CSV Column Headers
```
pr_number,title,author,created_at,request_to_review_timestamp,pr_approved_timestamp,review_given_timestamp,pr_merge_timestamp,is_closed,total_comments,total_updates
```

## Usage Examples

### Command Line Interface
```bash
# Generate stats for all PRs in repository
github-pr-stats --repo owner/repo-name --output stats.json

# Generate stats for specific date range
github-pr-stats --repo owner/repo-name --from 2024-01-01 --to 2024-01-31 --format csv

# Generate stats for specific author
github-pr-stats --repo owner/repo-name --author username --output author-stats.xlsx
```

### API Integration
```python
from github_pr_stats import PRStatsGenerator

generator = PRStatsGenerator(token="github_token")
stats = generator.generate_stats("owner/repo-name")
generator.export_csv(stats, "pr_stats.csv")
```

## Security Considerations

### Data Privacy
- Sanitize sensitive information from comments
- Respect repository privacy settings
- Implement proper access controls
- Consider GDPR compliance for EU users

### Token Security
- Store GitHub tokens securely
- Implement token rotation
- Use environment variables for token storage
- Audit token usage and permissions

## Monitoring and Reporting

### Metrics to Track
- API request count and rate limit usage
- Processing time per repository
- Error rates and types
- Data freshness and accuracy

### Alerts
- API rate limit approaching
- Authentication failures
- Data processing errors
- Unusual patterns in PR statistics
