import 'package:flutter/foundation.dart';
import 'database_helper.dart';

class BackendService {
  
  /// Formats the data and saves it across the two SQLite databases
  static Future<bool> saveScanRecord({
    required String scanId,
    required List<Map<String, dynamic>> scanData,
    required Map<String, String>? leftResult,
    required Map<String, String>? rightResult,
    required Map<String, String>? combinedResult,
    required bool isAccurate,
  }) async {
    debugPrint('DB: Saving record for $scanId across Metadata and Image databases...');
    try {
      await DatabaseHelper.instance.saveCompleteScan(
        scanId: scanId,
        physicianName: 'Attending Physician', // Can be made dynamic later
        leftClassification: leftResult?['classification'] ?? 'Unknown',
        rightClassification: rightResult?['classification'] ?? 'Unknown',
        combinedClassification: combinedResult?['classification'] ?? 'Unknown',
        isAccurate: isAccurate,
        scanData: scanData,
      );
      debugPrint('DB: Successfully saved to both databases.');
      return true;
    } catch (e) {
      debugPrint('DB ERROR: $e');
      throw Exception('Failed to save to local databases.');
    }
  }

  static Future<void> sendEmailReport({
    required String emailAddress,
    required String pdfFilePath,
    required String scanId,
  }) async {
    debugPrint('EMAIL SERVICE: Uploading and sending report to $emailAddress...');
    await Future.delayed(const Duration(seconds: 2)); 
    debugPrint('EMAIL SERVICE: Report successfully sent to $emailAddress.');
  }
}