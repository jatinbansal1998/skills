# Screenshots in a PR

Last verified: 2026-11-27

Never attach customer data, private screens or credentials; uploaded asset URLs are shareable.

1. **Capture** before and after, outside Git, with the repo's own screenshot script if it has
   one, else the Playwright CLI (`playwright screenshot`): desktop light, desktop dark
   (`--color-scheme dark`) and phone (`--viewport-size 390,844`), `--full-page`. Look at
   each PNG before uploading.

2. **Upload** with GitHub CLI native attachments. Check that `gh pr create --help` lists
   `--attach` (verified on `gh` 2.106.0); otherwise update `gh`, or report screenshots pending.
   Reference the local files in the body's `Before and after` table and pass each one:

   ```markdown
   | Before | After |
   |---|---|
   | ![Before: desktop light](./before.png) | ![After: desktop light](./after.png) |
   ```

   ```bash
   gh pr create --title "<title>" --body-file ./body.md --attach ./before.png --attach ./after.png
   gh pr edit <pr-url> --body-file ./body.md --attach ./before.png --attach ./after.png
   ```

   `gh` rewrites the references to GitHub asset URLs. Body references resolve from the body
   file's directory, `--attach` paths from the working directory; use absolute paths when
   they differ. A new page needs only the after image.

3. **Verify.** `gh pr view <pr-url> --json body` must show asset URLs, not local paths.
   Download each with `gh api <asset-url> > <tmp-file>` and `cmp` it with the local PNG; an
   unauthenticated download returns 404 on a private repo even after a good upload.

   A nonzero exit can still leave a created or updated PR with some uploads done. Inspect it,
   then `gh pr edit --attach` only the missing files. Never blindly create again.
