# Chrome Web Store Submission Checklist

## Before Submission

### Required Files ✅
- [x] manifest.json (v3)
- [x] Privacy Policy (privacy-policy.html)
- [x] Store description (STORE_LISTING.md)
- [x] Permission justifications (PERMISSION_JUSTIFICATIONS.md)
- [ ] Icon 16x16 (icon16.png) - **CREATE THIS**
- [x] Icon 48x48 (icon48.png)
- [x] Icon 128x128 (icon128.png)

### Screenshots (Need to Create)
- [ ] Screenshot 1: Popup in active state (1280x800)
- [ ] Screenshot 2: Dashboard overview (1280x800)
- [ ] Screenshot 3: Error capture flow (1280x800)
- [ ] Optional: Additional screenshots

### Promotional Images (Optional)
- [ ] Small promo tile (440x280)
- [ ] Large promo tile (920x680)
- [ ] Marquee (1400x560)

---

## Manifest Updates Needed

Update manifest.json to include icon16:
```json
"icons": {
  "16": "icon16.png",
  "48": "icon48.png",
  "128": "icon128.png"
}
```

---

## Developer Account Setup

1. Go to: https://chrome.google.com/webstore/devconsole
2. Pay one-time $5 registration fee
3. Verify your email/identity
4. Accept Developer Agreement

---

## Submission Steps

### Step 1: Package Extension
```bash
cd /Users/haimdayan/Desktop/FixOnce/extension
zip -r fixonce-extension.zip . -x "store/*" -x "*.md" -x ".DS_Store"
```

### Step 2: Upload to Chrome Web Store
1. Go to Developer Dashboard
2. Click "New Item"
3. Upload fixonce-extension.zip
4. Fill in store listing details

### Step 3: Store Listing
- **Name:** FixOnce - Error Trapper
- **Short desc:** Copy from STORE_LISTING.md
- **Full desc:** Copy from STORE_LISTING.md
- **Category:** Developer Tools
- **Language:** English

### Step 4: Privacy
- Upload privacy-policy.html to a public URL
- Enter Privacy Policy URL in dashboard
- Check "No personal data collected"

### Step 5: Screenshots
- Upload 1-5 screenshots (1280x800 or 640x400)
- Add captions for each

### Step 6: Permission Justifications
When prompted, explain each permission:
- Copy explanations from PERMISSION_JUSTIFICATIONS.md
- Be specific about why <all_urls> is needed
- Emphasize opt-in whitelist model

### Step 7: Submit for Review
- Click "Submit for Review"
- Wait 1-3 business days (usually)
- May take longer for first submission

---

## Common Rejection Reasons & How to Avoid

### 1. "Insufficient justification for host permissions"
**Solution:** Be very specific in justification. Explain whitelist model, that extension is inactive by default, and only monitors sites user explicitly enables.

### 2. "Missing privacy policy"
**Solution:** Host privacy-policy.html on a public URL (GitHub Pages, your server, etc.)

### 3. "Screenshots don't match functionality"
**Solution:** Use actual screenshots of the extension, not mockups.

### 4. "Description is misleading"
**Solution:** Don't overclaim. Be accurate about what the extension does.

### 5. "Code contains remote code loading"
**Solution:** Ensure all JS is bundled. No eval(), no loading scripts from external URLs.

---

## Post-Submission

### If Approved
- Extension goes live within 24 hours
- Share the Chrome Web Store link
- Update README with installation link

### If Rejected
- Read rejection reason carefully
- Make requested changes
- Resubmit with explanation of changes
- Use the "Reply" feature to communicate with reviewers

---

## Links

- Developer Dashboard: https://chrome.google.com/webstore/devconsole
- Developer Program Policies: https://developer.chrome.com/docs/webstore/program-policies
- Review Guidelines: https://developer.chrome.com/docs/webstore/review-process
- Publishing Guide: https://developer.chrome.com/docs/webstore/publish

---

## Files to Host Publicly

Before submitting, you need public URLs for:

1. **Privacy Policy**
   - Host privacy-policy.html somewhere public
   - Options: GitHub Pages, Netlify, your own domain
   - Example: https://fixonce.github.io/privacy-policy.html

2. **Support Page** (optional)
   - Can use GitHub Issues URL
   - https://github.com/fixonce/fixonce/issues

3. **Homepage** (optional)
   - Can use GitHub repo URL
   - https://github.com/fixonce/fixonce

---

## Quick Commands

```bash
# Package extension for upload
cd /Users/haimdayan/Desktop/FixOnce/extension
zip -r ../fixonce-extension.zip . -x "store/*" -x "*.md" -x ".DS_Store" -x "*.zip"

# Check zip contents
unzip -l ../fixonce-extension.zip
```
