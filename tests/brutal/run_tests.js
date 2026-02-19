const puppeteer = require('puppeteer');

(async () => {
  const browser = await puppeteer.launch({ 
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });
  
  try {
    const page = await browser.newPage();
    
    // Collect console logs and network errors
    const consoleLogs = [];
    const networkErrors = [];
    
    page.on('console', msg => {
      consoleLogs.push({
        type: msg.type(),
        text: msg.text()
      });
    });
    
    page.on('requestfailed', request => {
      networkErrors.push({
        url: request.url(),
        failure: request.failure()
      });
    });
    
    // Step 1: Open /v2 page
    console.log('Opening http://localhost:5000/v2...');
    await page.goto('http://localhost:5000/v2', { waitUntil: 'networkidle2' });
    
    // Get dashboard state from /v2
    const dashboardState = await page.evaluate(() => {
      // Try multiple selectors for the now card
      const nowCard = document.querySelector('[data-card="now"]') || 
                      document.querySelector('.now-card') ||
                      document.querySelector('#now-card');
      
      // Try multiple selectors for stats
      const statsElements = document.querySelectorAll('[data-stat]') || 
                           document.querySelectorAll('.stat-value') ||
                           [];
      
      // Also try to get visible text from main content
      const mainContent = document.querySelector('main') || document.body;
      const visibleText = mainContent ? mainContent.innerText.substring(0, 500) : '';
      
      return {
        nowCard: nowCard ? nowCard.textContent.trim() : 'not found',
        stats: Array.from(statsElements).map(el => ({
          name: el.getAttribute('data-stat') || el.className,
          value: el.textContent.trim()
        })),
        visibleText: visibleText
      };
    });
    
    console.log('\n=== DASHBOARD STATE (v2) ===');
    console.log('Now Card:', dashboardState.nowCard);
    console.log('Stats:', JSON.stringify(dashboardState.stats, null, 2));
    
    // Step 2: Open brutal test page
    console.log('\nOpening http://localhost:5000/test/brutal...');
    await page.goto('http://localhost:5000/test/brutal', { waitUntil: 'networkidle2' });
    
    // Wait for page to load
    await page.waitForSelector('#btn-reset');
    
    // Step 3: Click Reset Test Data
    console.log('Clicking "Reset Test Data"...');
    await page.click('#btn-reset');
    await new Promise(resolve => setTimeout(resolve, 1000)); // Wait for reset to complete
    
    // Step 4: Click Run All Tests
    console.log('Clicking "Run All Tests"...');
    await page.click('#btn-run');
    
    // Wait for tests to complete by monitoring the summary text
    console.log('Waiting for tests to complete...');
    await page.waitForFunction(
      () => {
        const summary = document.getElementById('summary');
        return summary && summary.textContent.includes('PASS=');
      },
      { timeout: 60000 }
    );
    
    // Give it a moment for final updates
    await new Promise(resolve => setTimeout(resolve, 1000));
    
    // Extract results
    const results = await page.evaluate(() => {
      const summary = document.getElementById('summary').textContent;
      const rows = Array.from(document.querySelectorAll('#rows tr'));
      
      return {
        summary,
        tests: rows.map(row => {
          const cells = row.querySelectorAll('td');
          return {
            id: cells[0]?.textContent.trim(),
            title: cells[1]?.textContent.trim(),
            status: cells[2]?.textContent.trim(),
            expected: cells[3]?.textContent.trim(),
            actual: cells[4]?.textContent.trim()
          };
        })
      };
    });
    
    // Parse summary
    const summaryMatch = results.summary.match(/PASS=(\d+) FAIL=(\d+) WARN=(\d+) TOTAL=(\d+)/);
    const summary = summaryMatch ? {
      pass: parseInt(summaryMatch[1]),
      fail: parseInt(summaryMatch[2]),
      warn: parseInt(summaryMatch[3]),
      total: parseInt(summaryMatch[4])
    } : null;
    
    // Output results
    console.log('\n=== TEST RESULTS ===');
    console.log(`Summary: PASS=${summary.pass} FAIL=${summary.fail} WARN=${summary.warn} TOTAL=${summary.total}`);
    
    console.log('\n=== FAILED/WARNED TESTS ===');
    const failedOrWarned = results.tests.filter(t => t.status === 'FAIL' || t.status === 'WARN');
    if (failedOrWarned.length === 0) {
      console.log('None - all tests passed!');
    } else {
      failedOrWarned.forEach(test => {
        console.log(`[${test.status}] ${test.id}`);
        console.log(`  Title: ${test.title}`);
        console.log(`  Expected: ${test.expected}`);
        console.log(`  Actual: ${test.actual}`);
        console.log('');
      });
    }
    
    console.log('\n=== CONSOLE ERRORS ===');
    const consoleErrors = consoleLogs.filter(log => log.type === 'error');
    if (consoleErrors.length === 0) {
      console.log('None');
    } else {
      consoleErrors.forEach(log => console.log(log.text));
    }
    
    console.log('\n=== NETWORK ERRORS ===');
    if (networkErrors.length === 0) {
      console.log('None');
    } else {
      networkErrors.forEach(err => {
        console.log(`${err.url}: ${err.failure?.errorText || 'unknown error'}`);
      });
    }
    
    // Save results to file
    const fs = require('fs');
    fs.writeFileSync(
      '/Users/haimdayan/Desktop/FixOnce/tests/brutal/automation_results.json',
      JSON.stringify({
        summary,
        dashboardState,
        tests: results.tests,
        consoleLogs,
        networkErrors,
        timestamp: new Date().toISOString()
      }, null, 2)
    );
    
    console.log('\n✓ Results saved to tests/brutal/automation_results.json');
    
  } catch (error) {
    console.error('Error running tests:', error);
    process.exit(1);
  } finally {
    await browser.close();
  }
})();
