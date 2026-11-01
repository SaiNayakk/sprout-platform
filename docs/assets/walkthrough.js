/**
 * docs/assets/walkthrough.js
 *
 * Single-source walkthrough mode for Sprout documentation pages.
 * Supports reading a page as standard documentation or as an interactive,
 * step-by-step card walkthrough.
 *
 * Detection:
 * Pages enable walkthrough mode either with YAML front matter:
 *   walkthrough: true
 * or by including the marker element near the top of the markdown:
 *   <div class="walkthrough-page"></div>
 * MkDocs Material parses front matter; the div marker guarantees detection
 * in the rendered DOM across all MkDocs configurations.
 */

(function () {
  'use strict';

  let activeInstance = null;

  function initWalkthrough() {
    if (activeInstance) {
      activeInstance.destroy();
      activeInstance = null;
    }

    const content = document.querySelector('.md-content__inner');
    if (!content) return;

    // Detect walkthrough enablement
    const marker = content.querySelector('.walkthrough-page');
    const metaTag = document.querySelector('meta[name="walkthrough"][content="true"]');
    if (!marker && !metaTag) {
      document.body.classList.remove('walkthrough-active');
      return;
    }

    activeInstance = new WalkthroughController(content, marker);
  }

  class WalkthroughController {
    constructor(contentEl, markerEl) {
      this.content = contentEl;
      this.marker = markerEl;
      this.isWalkthroughMode = false;
      this.currentStep = 0;
      this.steps = [];
      this.dots = [];
      this.totalH2Steps = 0;
      this.hasStep0 = false;

      this.init();
    }

    init() {
      const h2Elements = Array.from(this.content.querySelectorAll('h2'));
      if (h2Elements.length === 0) return;

      this.totalH2Steps = h2Elements.length;

      // Find page h1
      const h1 = this.content.querySelector('h1');

      // Create toggle banner at the top
      this.banner = document.createElement('div');
      this.banner.className = 'walkthrough-toggle-banner';

      this.toggleBtn = document.createElement('button');
      this.toggleBtn.type = 'button';
      this.toggleBtn.className = 'walkthrough-btn walkthrough-toggle-btn';
      this.toggleBtn.textContent = 'Walk me through it';
      this.toggleBtn.setAttribute('aria-label', 'Walk me through it');
      this.toggleBtn.addEventListener('click', () => this.toggleMode());

      this.banner.appendChild(this.toggleBtn);

      if (this.marker) {
        this.marker.parentNode.insertBefore(this.banner, this.marker);
        this.marker.style.display = 'none';
      } else if (h1 && h1.nextSibling) {
        h1.parentNode.insertBefore(this.banner, h1.nextSibling);
      } else {
        this.content.prepend(this.banner);
      }

      // Collect sibling nodes for Step 0 (content before first h2)
      const step0Nodes = [];
      const startRef = this.marker || this.banner;
      let sibling = startRef.nextSibling;
      while (sibling && sibling !== h2Elements[0]) {
        const next = sibling.nextSibling;
        if (sibling.nodeType === Node.ELEMENT_NODE ||
           (sibling.nodeType === Node.TEXT_NODE && sibling.textContent.trim().length > 0)) {
          step0Nodes.push(sibling);
        }
        sibling = next;
      }

      this.hasStep0 = step0Nodes.length > 0;

      // Step container
      this.stepsContainer = document.createElement('div');
      this.stepsContainer.className = 'walkthrough-steps-container';

      // Step 0 ("Overview")
      if (this.hasStep0) {
        const step0Div = document.createElement('section');
        step0Div.className = 'walkthrough-step';
        step0Div.setAttribute('data-step', '0');

        const step0Title = document.createElement('h2');
        step0Title.className = 'walkthrough-step-title walkthrough-step-0-title';
        step0Title.setAttribute('tabindex', '-1');
        step0Title.textContent = 'Overview';
        step0Div.appendChild(step0Title);

        step0Nodes.forEach(node => step0Div.appendChild(node));
        this.steps.push({
          index: 0,
          element: step0Div,
          title: 'Overview',
          titleEl: step0Title
        });
        this.stepsContainer.appendChild(step0Div);
      }

      // Steps 1..N (each h2 section)
      h2Elements.forEach((h2, idx) => {
        const stepNum = idx + 1;
        const stepDiv = document.createElement('section');
        stepDiv.className = 'walkthrough-step';
        stepDiv.setAttribute('data-step', String(stepNum));

        h2.classList.add('walkthrough-step-title');
        h2.setAttribute('tabindex', '-1');

        // Extract heading text without anchor symbol
        const headingClone = h2.cloneNode(true);
        const headerlink = headingClone.querySelector('.headerlink');
        if (headerlink) headerlink.remove();
        const headingText = headingClone.textContent.trim();

        // Collect sibling nodes until the next h2
        const nextH2 = h2Elements[idx + 1];
        const stepNodes = [h2];
        let curr = h2.nextSibling;
        while (curr && curr !== nextH2) {
          const next = curr.nextSibling;
          if (curr.nodeType === Node.ELEMENT_NODE ||
             (curr.nodeType === Node.TEXT_NODE && curr.textContent.trim().length > 0)) {
            stepNodes.push(curr);
          }
          curr = next;
        }

        stepNodes.forEach(node => stepDiv.appendChild(node));

        this.steps.push({
          index: stepNum,
          element: stepDiv,
          title: headingText,
          titleEl: h2
        });
        this.stepsContainer.appendChild(stepDiv);
      });

      // Construct walkthrough card wrapper
      this.card = document.createElement('div');
      this.card.className = 'walkthrough-card';

      // Header: Dots, Counter, Esc
      this.cardHeader = document.createElement('div');
      this.cardHeader.className = 'walkthrough-card-header';

      this.dotsContainer = document.createElement('div');
      this.dotsContainer.className = 'walkthrough-dots';
      this.dotsContainer.setAttribute('role', 'tablist');
      this.dotsContainer.setAttribute('aria-label', 'Walkthrough progress');

      this.steps.forEach(step => {
        const dot = document.createElement('button');
        dot.type = 'button';
        dot.className = 'walkthrough-dot';
        const label = (step.index === 0
          ? 'Step 0: Overview'
          : `Step ${step.index} of ${this.totalH2Steps}: ${step.title}`);
        dot.setAttribute('aria-label', label);
        dot.title = label;
        dot.addEventListener('click', () => this.goToStep(step.index));
        this.dotsContainer.appendChild(dot);
        this.dots.push(dot);
      });

      this.headerCounter = document.createElement('span');
      this.headerCounter.className = 'walkthrough-header-counter';

      this.escBtn = document.createElement('button');
      this.escBtn.type = 'button';
      this.escBtn.className = 'walkthrough-btn-text walkthrough-esc-btn';
      this.escBtn.textContent = '✕ Esc';
      this.escBtn.setAttribute('aria-label', 'Return to whole page mode');
      this.escBtn.title = 'Return to page mode (Esc)';
      this.escBtn.addEventListener('click', () => this.exitWalkthrough());

      this.cardHeader.appendChild(this.dotsContainer);
      this.cardHeader.appendChild(this.headerCounter);
      this.cardHeader.appendChild(this.escBtn);

      // Footer: Back button, Counter, Next button
      this.cardFooter = document.createElement('div');
      this.cardFooter.className = 'walkthrough-card-footer';

      this.backBtn = document.createElement('button');
      this.backBtn.type = 'button';
      this.backBtn.className = 'walkthrough-btn walkthrough-back-btn';
      this.backBtn.textContent = '← Back';
      this.backBtn.setAttribute('aria-label', 'Previous step');
      this.backBtn.addEventListener('click', () => {
        const prevIndex = this.getPrevStepIndex();
        if (prevIndex !== null) this.goToStep(prevIndex);
      });

      this.footerCounter = document.createElement('span');
      this.footerCounter.className = 'walkthrough-footer-counter';

      this.nextBtn = document.createElement('button');
      this.nextBtn.type = 'button';
      this.nextBtn.className = 'walkthrough-btn walkthrough-next-btn';
      this.nextBtn.textContent = 'Next →';
      this.nextBtn.setAttribute('aria-label', 'Next step');
      this.nextBtn.addEventListener('click', () => {
        const nextIndex = this.getNextStepIndex();
        if (nextIndex !== null) {
          this.goToStep(nextIndex);
        } else {
          this.exitWalkthrough();
        }
      });

      this.cardFooter.appendChild(this.backBtn);
      this.cardFooter.appendChild(this.footerCounter);
      this.cardFooter.appendChild(this.nextBtn);

      // Assemble card
      this.card.appendChild(this.cardHeader);
      this.card.appendChild(this.stepsContainer);
      this.card.appendChild(this.cardFooter);

      this.content.appendChild(this.card);

      // Screen-reader live region
      this.liveRegion = document.createElement('div');
      this.liveRegion.className = 'walkthrough-sr-only';
      this.liveRegion.setAttribute('aria-live', 'polite');
      this.liveRegion.setAttribute('aria-atomic', 'true');
      this.content.appendChild(this.liveRegion);

      // Check URL hash for direct step link
      this.checkInitialHash();
    }

    getPrevStepIndex() {
      const idx = this.steps.findIndex(s => s.index === this.currentStep);
      return idx > 0 ? this.steps[idx - 1].index : null;
    }

    getNextStepIndex() {
      const idx = this.steps.findIndex(s => s.index === this.currentStep);
      return idx < this.steps.length - 1 ? this.steps[idx + 1].index : null;
    }

    goToStep(stepNum, updateHash = true, moveFocus = true) {
      const stepObj = this.steps.find(s => s.index === stepNum);
      if (!stepObj) return;

      this.currentStep = stepNum;

      // Toggle active step
      this.steps.forEach(s => {
        if (s.index === stepNum) {
          s.element.classList.add('active');
        } else {
          s.element.classList.remove('active');
        }
      });

      // Update dots
      this.dots.forEach((dot, idx) => {
        const s = this.steps[idx];
        if (s.index === stepNum) {
          dot.classList.add('is-active');
          dot.setAttribute('aria-current', 'step');
        } else {
          dot.classList.remove('is-active');
          dot.removeAttribute('aria-current');
        }
      });

      // Format progress label
      const counterText = (stepNum === 0
        ? `Step 0 of ${this.totalH2Steps}`
        : `Step ${stepNum} of ${this.totalH2Steps}`);
      this.headerCounter.textContent = counterText;
      this.footerCounter.textContent = counterText;

      // Update Back / Next buttons
      const prevIdx = this.getPrevStepIndex();
      const nextIdx = this.getNextStepIndex();

      this.backBtn.disabled = (prevIdx === null);
      if (nextIdx === null) {
        this.nextBtn.textContent = 'Finish';
      } else {
        this.nextBtn.textContent = 'Next →';
      }

      // Keep step in URL hash
      if (updateHash) {
        const targetHash = `#step-${stepNum}`;
        if (window.location.hash !== targetHash) {
          history.pushState(null, '', targetHash);
        }
      }

      // Announce via aria-live
      const announcement = (stepNum === 0
        ? `Overview, Step 0 of ${this.totalH2Steps}`
        : `Step ${stepNum} of ${this.totalH2Steps}: ${stepObj.title}`);
      this.liveRegion.textContent = announcement;

      // Move focus to step title for screen-reader & keyboard users
      if (moveFocus && stepObj.titleEl) {
        stepObj.titleEl.focus();
      }

      // Scroll card into view
      const prefersReduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      this.card.scrollIntoView({ behavior: prefersReduced ? 'auto' : 'smooth', block: 'start' });
    }

    enterWalkthrough(stepNum = null) {
      this.isWalkthroughMode = true;
      document.body.classList.add('walkthrough-active');
      this.toggleBtn.textContent = 'Show the whole page';
      this.toggleBtn.setAttribute('aria-label', 'Show the whole page');

      let target = stepNum;
      if (target === null) {
        target = this.hasStep0 ? 0 : 1;
      }
      this.goToStep(target, true, true);
    }

    exitWalkthrough(updateHash = true) {
      this.isWalkthroughMode = false;
      document.body.classList.remove('walkthrough-active');
      this.toggleBtn.textContent = 'Walk me through it';
      this.toggleBtn.setAttribute('aria-label', 'Walk me through it');

      if (updateHash && window.location.hash && window.location.hash.startsWith('#step-')) {
        history.pushState(null, '', window.location.pathname + window.location.search);
      }

      // Scroll to current step title in page mode
      const stepObj = this.steps.find(s => s.index === this.currentStep);
      if (stepObj && stepObj.titleEl) {
        const prefersReduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        stepObj.titleEl.scrollIntoView({ behavior: prefersReduced ? 'auto' : 'smooth', block: 'start' });
        stepObj.titleEl.focus();
      }
    }

    toggleMode() {
      if (this.isWalkthroughMode) {
        this.exitWalkthrough();
      } else {
        this.enterWalkthrough();
      }
    }

    checkInitialHash() {
      const hash = window.location.hash;
      const match = hash.match(/^#step-(\d+)$/);
      if (match) {
        const stepNum = parseInt(match[1], 10);
        const exists = this.steps.some(s => s.index === stepNum);
        if (exists) {
          this.enterWalkthrough(stepNum);
          return;
        }
      }
      // Default: Page mode
      this.exitWalkthrough(false);
    }

    onHashChange() {
      const hash = window.location.hash;
      const match = hash.match(/^#step-(\d+)$/);
      if (match) {
        const stepNum = parseInt(match[1], 10);
        const exists = this.steps.some(s => s.index === stepNum);
        if (exists) {
          if (!this.isWalkthroughMode) {
            this.enterWalkthrough(stepNum);
          } else if (this.currentStep !== stepNum) {
            this.goToStep(stepNum, false, true);
          }
        }
      } else if (this.isWalkthroughMode) {
        this.exitWalkthrough(false);
      }
    }

    onKeyDown(e) {
      if (!this.isWalkthroughMode) return;
      const tag = (e.target && e.target.tagName) || '';
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(tag) || (e.target && e.target.isContentEditable)) {
        return;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        this.exitWalkthrough();
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        const prev = this.getPrevStepIndex();
        if (prev !== null) this.goToStep(prev);
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        const next = this.getNextStepIndex();
        if (next !== null) this.goToStep(next);
      }
    }

    destroy() {
      document.body.classList.remove('walkthrough-active');
    }
  }

  // Global event delegation for keydown and hashchange
  window.addEventListener('hashchange', function () {
    if (activeInstance) {
      activeInstance.onHashChange();
    }
  });

  document.addEventListener('keydown', function (e) {
    if (activeInstance) {
      activeInstance.onKeyDown(e);
    }
  });

  // MkDocs Material instant navigation hook
  if (typeof document$ !== 'undefined') {
    document$.subscribe(function () {
      initWalkthrough();
    });
  } else if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initWalkthrough);
  } else {
    initWalkthrough();
  }
})();
