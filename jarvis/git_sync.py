"""
GitHub synchronization module for Jarvis.
Handles git operations: stage, commit, push to remote.
"""

from git import Repo, InvalidGitRepositoryError, GitCommandError
from pathlib import Path
from datetime import datetime
from jarvis.config import REPO_PATH


def get_repo():
    """
    Load the git repository from REPO_PATH.
    
    Returns:
        git.Repo: Repository object
        
    Raises:
        RuntimeError: If REPO_PATH is not a git repository
    """
    try:
        return Repo(REPO_PATH)
    except InvalidGitRepositoryError:
        raise RuntimeError(
            f"devNote folder is not a git repo. "
            f"Run git init inside {REPO_PATH}"
        )


def get_status():
    """
    Get current git status of the repository.
    
    Returns:
        dict: Status information including branch, modified files, ahead count
    """
    repo = get_repo()
    
    # Calculate ahead count
    ahead_count = 0
    try:
        ahead_count = len(list(repo.iter_commits('origin/main..HEAD')))
    except Exception:
        ahead_count = 0
    
    return {
        "branch": repo.active_branch.name,
        "is_dirty": repo.is_dirty(untracked_files=True),
        "untracked": [item for item in repo.untracked_files],
        "modified": [item.a_path for item in repo.index.diff(None)],
        "staged": [item.a_path for item in repo.index.diff("HEAD")],
        "ahead": ahead_count,
    }


def stage_and_commit(message=None):
    """
    Stage all changes and commit to the repository.
    
    Args:
        message (str, optional): Custom commit message. 
                               If None, generates default message.
    
    Returns:
        dict: Commit result with committed status, message, and sha
    """
    repo = get_repo()
    
    # Check if there's anything to commit
    if not repo.is_dirty(untracked_files=True):
        return {"committed": False, "message": "Nothing to commit"}
    
    # Stage all changes
    repo.git.add(A=True)
    
    # Build commit message if not provided
    if message is None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        message = f"feat: jarvis auto-sync {now}"
    
    # Create commit
    commit = repo.index.commit(message)
    
    return {
        "committed": True,
        "message": message,
        "sha": commit.hexsha[:7]
    }


def push_to_remote():
    """
    Push commits to the remote repository.
    
    Returns:
        dict: Push result with status and remote URL or error
    """
    repo = get_repo()
    
    # Check if origin remote exists
    if "origin" not in [r.name for r in repo.remotes]:
        return {"pushed": False, "error": "No remote named origin found"}
    
    try:
        # Push to origin
        repo.remotes.origin.push()
        return {"pushed": True, "remote": repo.remotes.origin.url}
    except GitCommandError as e:
        return {"pushed": False, "error": str(e)}


def sync(commit_message=None):
    """
    Main sync function: stage, commit, and push changes.
    
    Args:
        commit_message (str, optional): Custom commit message
    
    Returns:
        dict: Sync result with status, commit info, and any errors
    """
    # Stage and commit
    commit_result = stage_and_commit(commit_message)
    
    if not commit_result["committed"]:
        return {"synced": False, "reason": "nothing to commit"}
    
    # Push to remote
    push_result = push_to_remote()
    
    if not push_result["pushed"]:
        return {
            "synced": False,
            "committed": True,
            "push_error": push_result.get("error", "Unknown error")
        }
    
    return {
        "synced": True,
        "committed": True,
        "pushed": True,
        "commit_sha": commit_result["sha"],
        "commit_message": commit_result["message"]
    }


def build_commit_message(classification, text):
    """
    Build a descriptive git commit message from classification and text.
    
    Args:
        classification (dict): Classification result with type, domain, subdomain, tags
        text (str): Original note text
    
    Returns:
        str: Formatted commit message
    """
    note_type = classification.get("type", "note")
    domain = classification.get("domain", "general")
    
    # Extract title from text (first line or first 50 chars)
    title = text.split('\n')[0].strip()
    if len(title) > 50:
        title = title[:50].rsplit(' ', 1)[0] + "..."
    
    message = f"feat: add {note_type} note — {title} [{domain}]"
    return message
