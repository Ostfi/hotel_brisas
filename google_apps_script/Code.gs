function doPost(e) {
  const expectedToken = PropertiesService
    .getScriptProperties()
    .getProperty('RELAY_TOKEN');
  if (!expectedToken) {
    return jsonResponse_({ ok: false, error: 'Relay token is not configured.' });
  }

  if (!e || !e.postData || !e.postData.contents) {
    return jsonResponse_({ ok: false, error: 'Request body is missing.' });
  }

  let data;
  try {
    data = JSON.parse(e.postData.contents);
  } catch (error) {
    return jsonResponse_({ ok: false, error: 'Invalid JSON request.' });
  }

  if (!data || data.token !== expectedToken) {
    return jsonResponse_({ ok: false, error: 'Unauthorized request.' });
  }

  const to = normalizeAddresses_(data.to);
  const cc = normalizeAddresses_(data.cc);
  const bcc = normalizeAddresses_(data.bcc);
  if (to.length === 0) {
    return jsonResponse_({ ok: false, error: 'No valid recipient was provided.' });
  }

  if (to.length + cc.length + bcc.length > 20) {
    return jsonResponse_({ ok: false, error: 'Too many recipients.' });
  }

  const subject = typeof data.subject === 'string' ? data.subject : '';
  const body = typeof data.body === 'string' ? data.body : '';
  if (!subject || !body) {
    return jsonResponse_({ ok: false, error: 'Subject and body are required.' });
  }

  const options = {};
  if (cc.length > 0) {
    options.cc = cc.join(',');
  }
  if (bcc.length > 0) {
    options.bcc = bcc.join(',');
  }
  if (typeof data.replyTo === 'string' && data.replyTo) {
    options.replyTo = data.replyTo;
  }
  if (typeof data.htmlBody === 'string' && data.htmlBody) {
    options.htmlBody = data.htmlBody;
  }

  try {
    GmailApp.sendEmail(to.join(','), subject, body, options);
  } catch (error) {
    console.error('GmailApp.sendEmail failed:', error);
    return jsonResponse_({
      ok: false,
      error: 'Gmail could not send the message. Check Apps Script executions.',
    });
  }

  return jsonResponse_({ ok: true });
}

function normalizeAddresses_(addresses) {
  if (!Array.isArray(addresses)) {
    return [];
  }
  return addresses
    .filter(function (address) {
      return typeof address === 'string';
    })
    .map(function (address) {
      return address.trim();
    })
    .filter(function (address) {
      return address.length > 0;
    });
}

function jsonResponse_(body) {
  return ContentService
    .createTextOutput(JSON.stringify(body))
    .setMimeType(ContentService.MimeType.JSON);
}
