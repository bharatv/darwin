# Darwin Release Guide (Quick Start)

## 🚀 Two Ways to Build Images

Darwin uses a **single master release workflow** that builds all 15 images together. There are two ways to trigger it:

1. **Production Release** (via GitHub Release) - Recommended for official releases
   - Triggered by creating a GitHub Release
   - Tags images with version AND `:latest` tag
   - Example: `darwinhq/darwin-catalog:1.0.0` + `darwinhq/darwin-catalog:latest`

2. **Manual Testing Build** (via workflow dispatch) - For testing and RC versions
   - Triggered manually from Actions tab or CLI
   - Tags images with version ONLY (no `:latest` tag)
   - Example: `darwinhq/darwin-catalog:1.0.0-rc1` (no latest tag)

### What Gets Built (15 Images)

**Base Images (3):**
- `darwinhq/python:3.9.7-pip-bookworm-slim`
- `darwinhq/java:11-maven-bookworm-slim`
- `darwinhq/golang:1.18-bookworm-slim`

**Darwin Applications (8):**
- `darwinhq/darwin-catalog`
- `darwinhq/darwin-compute`
- `darwinhq/darwin-cluster-manager`
- `darwinhq/darwin-mlflow`
- `darwinhq/darwin-mlflow-app`
- `darwinhq/ml-serve-app`
- `darwinhq/artifact-builder`
- `darwinhq/darwin-workflow`

**Runtime Images (4):**
- `darwinhq/ray:2.37.0`
- `darwinhq/ray:2.53.0`
- `darwinhq/ray:2.37.0-darwin-sdk`
- `darwinhq/serve-md-runtime:latest`

---

## Method 1: Production Release (Recommended)

Build and publish official releases with `:latest` tags.

### Step 1: Merge Changes to Main

Get your code ready for release.

**Via UI:**
1. Create PR with your changes
2. Get approval
3. **Squash and merge** to `main`

**Via CLI:**
```bash
# After PR approval
gh pr merge --squash
git checkout main && git pull
```

---

### Step 2: Create GitHub Release

This triggers the build of **all 15 images**.

**Via UI:**
1. Go to **Code** tab → **Releases** → **Draft a new release**
2. **Choose a tag:** Type `v1.0.0` → **"Create new tag: v1.0.0 on publish"**
3. **Target:** Select `main` branch ✅
4. **Release title:** `Darwin Platform v1.0.0`
5. **Description:** (Optional) Add release notes
6. Click **"Publish release"** 🚀

**Via CLI:**
```bash
git checkout main && git pull
git tag v1.0.0 -m "Darwin Platform v1.0.0"
git push origin v1.0.0

# Or create a release
gh release create v1.0.0 --title "Darwin Platform v1.0.0" --notes "Release notes here"
```

**What Happens:**
- ✅ All 15 images build in parallel
- ✅ Each image tagged with version (e.g., `1.0.0`) + `:latest`
- ✅ Pushed to `darwinhq` organization on Docker Hub
- ✅ Detailed summary shows which images succeeded/failed

**Example Tags Created:**
- Applications: `darwinhq/darwin-catalog:1.0.0` + `darwinhq/darwin-catalog:latest`
- Base images: `darwinhq/python:3.9.7-pip-bookworm-slim-1.0.0` + `darwinhq/python:3.9.7-pip-bookworm-slim`
- Runtimes: `darwinhq/ray:2.37.0-1.0.0` + `darwinhq/ray:2.37.0`

---

## Method 2: Manual Testing Build

For testing, release candidates, or builds without updating `:latest` tags.

**Via UI:**
1. Go to **Actions** tab → **"🚀 Darwin Platform Release"**
2. Click **"Run workflow"** dropdown
3. Select **branch** (usually `main`)
4. Enter **Version** (e.g., `1.0.0-rc1`, `2.0.0-beta.1`, `test-build-123`)
5. Click **"Run workflow"** 🚀

**Via CLI:**
```bash
# Run from main branch
gh workflow run release.yml -f version=1.0.0-rc1

# Run from a specific branch
gh workflow run release.yml --ref feature-branch -f version=2.0.0-alpha

# Watch the workflow
gh run watch
```

**What Happens:**
- ✅ All 15 images build in parallel
- ✅ Each image tagged with your custom version ONLY (no `:latest` tag)
- ✅ Pushed to `darwinhq` organization on Docker Hub
- ✅ Detailed summary shows which images succeeded/failed

**Example Tags Created:**
- Applications: `darwinhq/darwin-catalog:1.0.0-rc1` (no latest tag)
- Base images: `darwinhq/python:3.9.7-pip-bookworm-slim-1.0.0-rc1` (no default tag)
- Runtimes: `darwinhq/ray:2.37.0-1.0.0-rc1` (no default tag)

**When to Use Manual Builds:**
- 🧪 Testing changes before official release
- 🏗️ Building release candidates (RC)
- 🐛 Creating bug fix test builds
- 🔬 Experimenting with new features
- 📦 Building from feature branches

---

## Build Summary Examples

After either workflow completes, you'll see a detailed summary:

### Production Release Summary
```
## 🚀 Darwin Platform v1.0.0 Release Summary

**Build Results:** 15/15 successful

### Base Images (3)
✅ Base: python (darwinhq/python:3.9.7-pip-bookworm-slim)
✅ Base: java (darwinhq/java:11-maven-bookworm-slim)
✅ Base: golang (darwinhq/golang:1.18-bookworm-slim)

### Darwin Applications (8)
✅ App: darwin-catalog
✅ App: darwin-compute
✅ App: darwin-cluster-manager
✅ App: darwin-mlflow
✅ App: darwin-mlflow-app
✅ App: ml-serve-app
✅ App: artifact-builder
✅ App: darwin-workflow

### Runtime Images (4)
✅ Runtime: ray-2.37.0 (darwinhq/ray:2.37.0)
✅ Runtime: ray-2.53.0 (darwinhq/ray:2.53.0)
✅ Runtime: ray-darwin-sdk (darwinhq/ray:2.37.0-darwin-sdk)
✅ Runtime: serve-runtime (darwinhq/serve-md-runtime:latest)

---

## 🎉 All Images Built Successfully!

All 15 images have been pushed to darwinhq organization on Docker Hub.

**Registry:** docker.io/darwinhq
**Version:** v1.0.0
**Tags:** Each image tagged with v1.0.0 + :latest
```

### Manual Testing Build Summary
```
## 🚀 Darwin Platform 1.0.0-rc1 Release Summary

**Build Results:** 15/15 successful

[... same image list ...]

## 🎉 All Images Built Successfully!

All 15 images have been pushed to darwinhq organization on Docker Hub.

**Registry:** docker.io/darwinhq
**Version:** 1.0.0-rc1
**Tags:** Each image tagged with 1.0.0-rc1 only (no :latest)
```

---

## Partial Success Support

If some images fail to build, the workflow continues and shows what succeeded:

```
**Build Results:** 12/15 successful

### Failed Builds (3)
❌ App: darwin-cluster-manager
❌ Runtime: ray-darwin-sdk
❌ Runtime: serve-runtime

⚠️ Warning: Some images failed to build. Check individual job logs for details.
```

**Benefits:**
- ✅ See which images built successfully
- ✅ Deploy services that succeeded
- ✅ Identify failures quickly
- ✅ Re-run workflow to retry failures

---

## Monitor Release Progress

**Via UI:**
1. Go to **Actions** tab
2. Click on **"🚀 Darwin Platform Release"** workflow
3. See all 3 parallel jobs:
   - Build Base Images (3 images in parallel)
   - Build Darwin Applications (8 images in parallel)
   - Build Runtime Images (4 images in parallel)
4. Click any job to see detailed logs

**Via CLI:**
```bash
# List recent releases
gh run list --workflow=release.yml --limit 5

# Watch a specific release
gh run watch

# View detailed logs
gh run view <run-id> --log
```

---

## Verify Released Images

Pull images from either production releases or manual builds:

```bash
# --- Production Release (with :latest tags) ---
# Applications
docker pull darwinhq/darwin-catalog:1.0.0
docker pull darwinhq/darwin-catalog:latest  # ← Only available for releases

# Base images
docker pull darwinhq/python:3.9.7-pip-bookworm-slim-1.0.0
docker pull darwinhq/python:3.9.7-pip-bookworm-slim  # ← Only available for releases

# Runtimes
docker pull darwinhq/ray:2.37.0-1.0.0
docker pull darwinhq/ray:2.37.0  # ← Only available for releases

# --- Manual Testing Build (version only, no :latest) ---
# Applications
docker pull darwinhq/darwin-catalog:1.0.0-rc1
docker pull darwinhq/darwin-workflow:2.0.0-beta.1

# Base images
docker pull darwinhq/python:3.9.7-pip-bookworm-slim-1.0.0-rc1

# Runtimes
docker pull darwinhq/ray:2.37.0-1.0.0-rc1
```


## ⚙️ One-Time Setup

**Add Docker Hub secrets** (required before first release):

1. Go to **Settings** tab → **Secrets and variables** → **Actions**
2. Click **"New repository secret"**
3. Add these secrets:
   - **Name:** `DOCKERHUB_USERNAME`  
     **Value:** `darwinhq`
   - **Name:** `DOCKERHUB_TOKEN`  
     **Value:** Your Docker Hub access token

Get token: https://hub.docker.com/settings/security

---

## 🎯 Release Checklist

### For Production Releases:

- [ ] All changes merged to `main` branch
- [ ] Local tests passing
- [ ] CI/CD tests passing
- [ ] Version number decided (e.g., `v1.0.0`)
- [ ] Release notes prepared (optional)
- [ ] Ready to update `:latest` tags

**Then:** Create GitHub Release and all images build automatically!

### For Manual Testing Builds:

- [ ] Branch to build from is ready
- [ ] Version name decided (e.g., `1.0.0-rc1`, `test-build-123`)
- [ ] Understand that `:latest` tags won't be updated

**Then:** Manually trigger workflow from Actions tab or CLI!

---

## 📋 Version Naming

Use semantic versioning for releases:

- `v1.0.0` - Major release (breaking changes)
- `v1.1.0` - Minor release (new features)
- `v1.1.1` - Patch release (bug fixes)
- `v1.0.0-rc1` - Release candidate (testing)
- `v2.0.0-beta.1` - Beta release (pre-release)

All images use the same version (cohesive release).

---

## Troubleshooting

### Some images failed to build

1. Check the workflow summary for failed images
2. Click on the failed job to see error logs
3. Fix the issue in code
4. **For production:** Create a new release to retry
5. **For testing:** Manually trigger workflow again with a new version

### Workflow not triggering

**For production releases:**
- Ensure you created a **Release**, not just a tag
- Release must be **published**, not draft
- Check that secrets are set correctly

**For manual builds:**
- Check that you're on the correct branch
- Ensure secrets are available in the repository
- Use `gh run watch` to monitor workflow start

### Base image errors

If base images fail, dependent applications will also fail. Fix base images first, then re-run the release.

### Wrong tags created

**Problem:** `:latest` tags were updated when you didn't want them to be.
**Solution:** Use **Method 2: Manual Testing Build** instead of creating a GitHub Release.

**Problem:** `:latest` tags were NOT updated when you wanted them to be.
**Solution:** Use **Method 1: Production Release** by creating a GitHub Release, not manual trigger.

---

## Quick Reference

| Goal | Method | Trigger | Tags Created |
|------|--------|---------|--------------|
| Official release | Production Release | Create GitHub Release | `version` + `:latest` |
| Test/RC build | Manual Testing | Actions → Run workflow | `version` only |
| Bug fix test | Manual Testing | CLI: `gh workflow run` | `version` only |
| Feature branch test | Manual Testing | Specify branch in UI/CLI | `version` only |

---

**That's it!** Choose your method and watch all 15 images build automatically. 🎉
