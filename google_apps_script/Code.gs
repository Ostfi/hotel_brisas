function doPost(e) {
  let expectedToken = '';
  try {
    expectedToken = PropertiesService
      .getScriptProperties()
      .getProperty('RELAY_TOKEN');
    return handlePost_(e, expectedToken);
  } catch (error) {
    const detail = safeErrorMessage_(error, expectedToken);
    console.error('Unhandled doPost error:', detail);
    return jsonResponse_({ ok: false, error: 'Apps Script: ' + detail });
  }
}

function handlePost_(e, expectedToken) {
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
    const detail = safeErrorMessage_(error, expectedToken);
    console.error('GmailApp.sendEmail failed:', detail);
    return jsonResponse_({
      ok: false,
      error: 'Gmail could not send the message: ' + detail,
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

function safeErrorMessage_(error, token) {
  let detail = (
    error && error.message
      ? String(error.message)
      : 'Unexpected Apps Script error.'
  );
  if (token) {
    detail = detail.split(token).join('[secret redacted]');
  }
  detail = detail.replace(
    /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi,
    '[email redacted]',
  );
  return detail.substring(0, 300);
}

function jsonResponse_(body) {
  return ContentService
    .createTextOutput(JSON.stringify(body))
    .setMimeType(ContentService.MimeType.JSON);
}
