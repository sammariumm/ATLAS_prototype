import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:mailer/mailer.dart';
import 'package:mailer/smtp_server.dart';

class BackendService {
  // --- THESIS EMAIL CONFIGURATION ---
  // Put your dedicated thesis sender email and generated App Password here
  static const String senderEmail = 'barbeyto.mikkoloeiroc06@gmail.com';
  static const String appPassword = 'nsme qpzy pmyq lkhy';

  static Future<void> saveToDatabase({
    required String scanId,
    required String? physicianName,
    required String? email,
  }) async {
    debugPrint('DB: Saving metadata for $scanId...');
    await Future.delayed(const Duration(milliseconds: 500));
  }

  static Future<bool> sendToBlockchain({
    required String scanId,
    required List<Map<String, dynamic>> scanData,
    required String combinedClassification,
    required bool isAccurate,
  }) async {
    debugPrint('BLOCKCHAIN: Minting record for $scanId...');
    await Future.delayed(const Duration(seconds: 2));
    return true;
  }

  /// Actually sends the email with the PDF attached via Gmail SMTP
  static Future<void> sendEmailReport({
    required String emailAddress,
    required String pdfFilePath,
    required String scanId,
  }) async {
    debugPrint(
      'EMAIL SERVICE: Preparing to send real email to $emailAddress...',
    );

    // 1. Configure the SMTP server
    final smtpServer = gmail(senderEmail, appPassword);

    // 2. Create the email message
    final message = Message()
      ..from = Address(senderEmail, 'ATLAS-BC System')
      ..recipients.add(emailAddress)
      ..subject = 'ATLAS-BC Medical Report - $scanId'
      ..text =
          'Hello,\n\nPlease find attached the automated AI analysis and physician validation report for Scan ID: $scanId.\n\nRegards,\nATLAS-BC Automated System';

    // 3. Attach the generated PDF
    if (pdfFilePath.isNotEmpty) {
      final file = File(pdfFilePath);
      if (await file.exists()) {
        message.attachments.add(FileAttachment(file));
      } else {
        debugPrint('EMAIL ERROR: PDF file not found at $pdfFilePath');
      }
    }

    // 4. Send the email
    try {
      final sendReport = await send(message, smtpServer);
      debugPrint(
        'EMAIL SERVICE: Success! Message sent: ${sendReport.toString()}',
      );
    } on MailerException catch (e) {
      debugPrint('EMAIL SERVICE ERROR: Message not sent.');
      for (var p in e.problems) {
        debugPrint('Problem: ${p.code}: ${p.msg}');
      }
      throw Exception('Failed to send email. Check credentials or network.');
    }
  }
}
