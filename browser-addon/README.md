# Browser addons

Thanks to the non compatibility of manifest formats between firefox and chrom, we need two different folders, with everything in sync, except for
both `manifest.json` files that are links to `manifest-firefox.json` and `manifest-chrome.json`.

When updating something in the `src` folder, you can `cp -a src/* firefox/*` and `cp -a src/* chrom/*`
