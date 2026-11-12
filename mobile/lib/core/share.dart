import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:share_plus/share_plus.dart';

/// Opens the system share sheet with [text]. Overridden in tests.
typedef Sharer = Future<void> Function(String text, {String? subject});

Future<void> _systemShare(String text, {String? subject}) async {
  await SharePlus.instance.share(ShareParams(text: text, subject: subject));
}

final sharerProvider = Provider<Sharer>((ref) => _systemShare);

/// Opens the share sheet with a file (save to Files or Drive, send on WhatsApp...).
typedef FileSharer = Future<void> Function(Uint8List bytes, String filename, {String mimeType});

Future<void> _systemShareFile(Uint8List bytes, String filename, {String mimeType = 'application/pdf'}) async {
  await SharePlus.instance.share(
    ShareParams(
      files: [XFile.fromData(bytes, mimeType: mimeType, name: filename)],
      fileNameOverrides: [filename],
      subject: filename,
    ),
  );
}

final fileSharerProvider = Provider<FileSharer>((ref) => _systemShareFile);

/// Adds the app signature to shared text.
String withSignature(String text) => '$text\n\n— via InsightPulse AI';
