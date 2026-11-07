import 'dart:io';
import 'package:flutter/material.dart';
import '../services/backend_service.dart';

class ResultsPanel extends StatefulWidget {
  /// The four views of the exam in the order Left CC, Left MLO, Right CC, Right MLO (empty until the AI has run).
  /// Each entry: side, view, status ('captured' or 'na'), image_path, preview_path.
  final List<Map<String, dynamic>> scanData;
  final String? scanId;
  final Map<String, String>? leftResult;  // null = left breast not available
  final Map<String, String>? rightResult; // null = right breast not available
  final Map<String, String>? combinedResult;
  final String note; // e.g. "a view was missing, a copy of the other view was used"
  final VoidCallback onNewPatient;

  const ResultsPanel({
    super.key,
    required this.scanData,
    this.scanId,
    this.leftResult,
    this.rightResult,
    this.combinedResult,
    this.note = '',
    required this.onNewPatient,
  });

  @override
  State<ResultsPanel> createState() => _ResultsPanelState();
}

class _ResultsPanelState extends State<ResultsPanel> {
  bool? _isAccurate;
  bool _isSubmitting = false;
  bool? _savedVerdict; // the verdict already stored in the database for the current analysis

  bool get _hasResult => widget.combinedResult != null && widget.scanData.isNotEmpty;

  @override
  void didUpdateWidget(ResultsPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    // A new analysis (for example after a view was retaken) makes the earlier accurate / inaccurate verdict obsolete.
    if (!identical(oldWidget.combinedResult, widget.combinedResult) ||
        !identical(oldWidget.leftResult, widget.leftResult) ||
        !identical(oldWidget.rightResult, widget.rightResult)) {
      _isAccurate = null;
      _savedVerdict = null;
    }
  }

  /// The picture shown on screen: the small JPEG preview (always 8-bit), or the PNG if there is no preview.
  String _displayPath(Map<String, dynamic> scan) {
    final String preview = (scan['preview_path'] ?? '').toString();
    if (preview.isNotEmpty) return preview;
    return (scan['image_path'] ?? '').toString();
  }

  void _showEnlargedImage(String path, String label) {
    if (path.isEmpty) return;
    showDialog(
      context: context,
      builder: (context) => Dialog(
        backgroundColor: Colors.black,
        insetPadding: EdgeInsets.zero,
        child: Stack(
          alignment: Alignment.topRight,
          children: [
            SizedBox(width: double.infinity, height: double.infinity, child: Image.file(File(path), fit: BoxFit.contain)),
            Positioned(
              top: 24, left: 16,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                color: Colors.black87,
                child: Text(label, style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(16.0),
              child: ElevatedButton(
                style: ElevatedButton.styleFrom(backgroundColor: Colors.red, padding: const EdgeInsets.all(16)),
                onPressed: () => Navigator.of(context).pop(),
                child: const Text('CLOSE', style: TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.bold)),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _handleSubmit() async {
    final bool? verdict = _isAccurate;
    if (verdict == null || !_hasResult || widget.scanId == null) return;
    setState(() => _isSubmitting = true);

    try {
      await BackendService.saveScanRecord(
        scanId: widget.scanId!,
        scanData: widget.scanData,
        leftResult: widget.leftResult,
        rightResult: widget.rightResult,
        combinedResult: widget.combinedResult,
        isAccurate: verdict,
      );
      if (mounted) {
        setState(() => _savedVerdict = verdict);
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Saved to Database!'), backgroundColor: Color(0xFF0D9488)));
      }
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Database Error'), backgroundColor: Colors.red));
    } finally {
      if (mounted) setState(() => _isSubmitting = false);
    }
  }

  // ------------------------------------------------------------ the four views
  Widget _buildViews() {
    if (widget.scanData.isEmpty) {
      return const Center(
        child: Text(
          'No images yet.\nCapture or import the views on the Camera tab, then press ANALYZE.',
          textAlign: TextAlign.center,
          style: TextStyle(color: Colors.white54, fontSize: 15),
        ),
      );
    }
    final List<Map<String, dynamic>> left = widget.scanData.where((s) => s['side'] == 'Left').toList();
    final List<Map<String, dynamic>> right = widget.scanData.where((s) => s['side'] == 'Right').toList();
    return Row(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Expanded(child: _breastGroup('LEFT BREAST', left)),
        const SizedBox(width: 8),
        Expanded(child: _breastGroup('RIGHT BREAST', right)),
      ],
    );
  }

  Widget _breastGroup(String title, List<Map<String, dynamic>> views) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          title,
          textAlign: TextAlign.center,
          style: const TextStyle(color: Colors.white70, fontSize: 12, fontWeight: FontWeight.bold, letterSpacing: 1.0),
        ),
        const SizedBox(height: 4),
        Expanded(
          child: Row(
            children: [
              for (final scan in views) Expanded(child: _viewTile(scan)),
            ],
          ),
        ),
      ],
    );
  }

  Widget _viewTile(Map<String, dynamic> scan) {
    final bool available = scan['status'] == 'captured' && _displayPath(scan).isNotEmpty;
    final String path = _displayPath(scan);
    final String label = '${scan['side'] == 'Left' ? 'L' : 'R'} ${scan['view']}';
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 2),
      child: GestureDetector(
        onTap: available ? () => _showEnlargedImage(path, label) : null,
        child: Container(
          clipBehavior: Clip.antiAlias,
          decoration: BoxDecoration(
            color: Colors.black,
            border: Border.all(color: Colors.grey.shade800),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Stack(
            fit: StackFit.expand,
            children: [
              if (available)
                Image.file(
                  File(path),
                  fit: BoxFit.contain,
                  errorBuilder: (context, error, stack) =>
                      const Center(child: Icon(Icons.broken_image, color: Colors.white38, size: 28)),
                )
              else
                const Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.block, color: Colors.white38, size: 28),
                      SizedBox(height: 4),
                      Text(
                        'NOT\nAVAILABLE',
                        textAlign: TextAlign.center,
                        style: TextStyle(color: Colors.white38, fontSize: 11),
                      ),
                    ],
                  ),
                ),
              Positioned(
                bottom: 4, left: 4,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
                  color: Colors.black87,
                  child: Text(label, style: const TextStyle(color: Colors.white, fontSize: 11)),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  // ----------------------------------------------------------------- results
  Widget _breastCard(String title, Map<String, String>? result) {
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: Colors.grey.shade300),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: const TextStyle(color: Color(0xFF64748B), fontWeight: FontWeight.bold, fontSize: 12)),
          const SizedBox(height: 4),
          Text(
            result != null ? (result['classification'] ?? '--') : 'Not available',
            style: TextStyle(
              color: result != null ? const Color(0xFF0F172A) : const Color(0xFF94A3B8),
              fontSize: result != null ? 20 : 16,
              fontWeight: FontWeight.bold,
            ),
          ),
          if (result != null)
            Text(
              'Confidence: ${result['confidence'] ?? '--'}',
              style: const TextStyle(color: Color(0xFF0D9488), fontSize: 13, fontWeight: FontWeight.bold),
            ),
        ],
      ),
    );
  }

  Widget _buildNote() {
    return Container(
      margin: const EdgeInsets.only(top: 12),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: const Color(0xFFFEF3C7),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFFF59E0B)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.info_outline, size: 18, color: Color(0xFF92400E)),
          const SizedBox(width: 8),
          Expanded(
            child: Text(widget.note, style: const TextStyle(fontSize: 13, color: Color(0xFF92400E))),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final Map<String, String>? combined = widget.combinedResult;
    final bool verdictSaved = _savedVerdict != null && _savedVerdict == _isAccurate;

    return Column(
      children: [
        Expanded(
          flex: 4,
          child: Container(
            color: const Color(0xFF1E293B),
            padding: const EdgeInsets.all(8),
            child: _buildViews(),
          ),
        ),
        Expanded(
          flex: 6,
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(16.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text('COMBINED AI RESULT', style: TextStyle(color: Color(0xFF64748B), fontWeight: FontWeight.bold, fontSize: 14)),
                const SizedBox(height: 8),
                Text(combined?['classification'] ?? '--', style: const TextStyle(color: Color(0xFF0F172A), fontSize: 32, fontWeight: FontWeight.bold)),
                Text('Confidence: ${combined?['confidence'] ?? '--'}', style: const TextStyle(color: Color(0xFF0D9488), fontSize: 18, fontWeight: FontWeight.bold)),
                if (combined != null && (combined['basis'] ?? '').isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 4),
                    child: Text('Based on: ${combined['basis']}', style: const TextStyle(color: Color(0xFF64748B), fontSize: 13)),
                  ),
                const SizedBox(height: 12),
                Text(combined?['recommendation'] ?? 'Awaiting Data...', style: const TextStyle(fontSize: 16, color: Color(0xFF0F172A))),
                if (widget.note.isNotEmpty) _buildNote(),
                const SizedBox(height: 12),
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(child: _breastCard('LEFT BREAST', widget.leftResult)),
                    const SizedBox(width: 12),
                    Expanded(child: _breastCard('RIGHT BREAST', widget.rightResult)),
                  ],
                ),
                const Divider(height: 24),
                Row(
                  children: [
                    Expanded(
                      child: ElevatedButton(
                        style: ElevatedButton.styleFrom(backgroundColor: _isAccurate == true ? const Color(0xFF0D9488) : Colors.white, side: const BorderSide(color: Color(0xFF0D9488)), padding: const EdgeInsets.symmetric(vertical: 16)),
                        onPressed: !_hasResult ? null : () => setState(() => _isAccurate = true),
                        child: Text('Accurate', textAlign: TextAlign.center, style: TextStyle(color: _isAccurate == true ? Colors.white : const Color(0xFF0D9488), fontSize: 16)),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: ElevatedButton(
                        style: ElevatedButton.styleFrom(backgroundColor: _isAccurate == false ? const Color(0xFFE11D48) : Colors.white, side: const BorderSide(color: Color(0xFFE11D48)), padding: const EdgeInsets.symmetric(vertical: 16)),
                        onPressed: !_hasResult ? null : () => setState(() => _isAccurate = false),
                        child: Text('Inaccurate', textAlign: TextAlign.center, style: TextStyle(color: _isAccurate == false ? Colors.white : const Color(0xFFE11D48), fontSize: 16)),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                ElevatedButton(
                  style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF0F172A), padding: const EdgeInsets.symmetric(vertical: 16)),
                  onPressed: (_isAccurate == null || _isSubmitting || !_hasResult || verdictSaved) ? null : _handleSubmit,
                  child: _isSubmitting
                      ? const CircularProgressIndicator(color: Colors.white)
                      : Text(verdictSaved ? 'VALIDATION SAVED' : 'SUBMIT VALIDATION', style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
                ),
                const SizedBox(height: 12),

                TextButton.icon(
                  style: TextButton.styleFrom(foregroundColor: Colors.red, padding: const EdgeInsets.symmetric(vertical: 16)),
                  onPressed: widget.onNewPatient, // Triggers global reset
                  icon: const Icon(Icons.delete_forever),
                  label: const Text('DISCARD SCAN & RESTART', style: TextStyle(fontSize: 14, fontWeight: FontWeight.bold)),
                )
              ],
            ),
          ),
        ),
      ],
    );
  }
}
