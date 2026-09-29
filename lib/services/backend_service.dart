import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:mailer/mailer.dart';
import 'package:mailer/smtp_server.dart';

/// Remote persistence stubs and Gmail delivery for ATLAS-BC reports.
class BackendService {
  /// Gmail sender — replace with env / secure storage for production deployments.
  static const String senderEmail = 'barbeyto.mikkoloeiroc06@gmail.com';
  static const String appPassword = 'nsme qpzy pmyq lkhy';

  /// Placeholder local DB write (replace with SQLite or cloud API).
  static Future<void> saveToDatabase({
    required String scanId,
    required String? physicianName,
    required String? email,
  }) async {
    debugPrint(
      'DB: Saving metadata for $scanId (physician: $physicianName, email: $email)',
    );
    await Future.delayed(const Duration(milliseconds: 500));
  }

  /// Placeholder ledger mint when the physician marks the AI output as accurate.
  static Future<bool> sendToBlockchain({
    required String scanId,
    required List<Map<String, dynamic>> scanData,
    required String combinedClassification,
    required bool isAccurate,
  }) async {
    debugPrint(
      'BLOCKCHAIN: Minting record for $scanId ($combinedClassification, accurate: $isAccurate)',
    );
    await Future.delayed(const Duration(seconds: 2));
    return true;
  }

  /// Sends the generated PDF report via Gmail SMTP.
  static Future<void> sendEmailReport({
    required String emailAddress,
    required String pdfFilePath,
    required String scanId,
  }) async {
    debugPrint('EMAIL: Sending report for $scanId to $emailAddress');

    final smtpServer = gmail(senderEmail, appPassword);

    final message = Message()
      ..from = Address(senderEmail, 'ATLAS-BC System')
      ..recipients.add(emailAddress)
      ..subject = 'ATLAS-BC Medical Report - $scanId'
      ..text =
          'Hello,\n\nPlease find attached the automated AI analysis and '
          'physician validation report for Scan ID: $scanId.\n\n'
          'Regards,\nATLAS-BC Automated System';

    if (pdfFilePath.isNotEmpty) {
      final file = File(pdfFilePath);
      if (await file.exists()) {
        message.attachments.add(FileAttachment(file));
      } else {
        debugPrint('EMAIL ERROR: PDF not found at $pdfFilePath');
      }
    }

    try {
      final sendReport = await send(message, smtpServer);
      debugPrint('EMAIL: Sent — ${sendReport.toString()}');
    } on MailerException catch (e) {
      debugPrint('EMAIL ERROR: Message not sent.');
      for (final p in e.problems) {
        debugPrint('Problem: ${p.code}: ${p.msg}');
      }
      throw Exception('Failed to send email. Check credentials or network.');
    }
  }
}
